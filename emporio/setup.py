"""Configuração da loja pelo dono, no terminal: login e escolha da IA (local ou API).

    python -m emporio.setup

Primeiro acesso cria o login do dono (senha guardada só como hash scrypt). Depois, com
login, o dono escolhe a IA: local (Ollama) ou API (OpenAI, Gemini, Claude) com a chave.
A escolha fica em data/orfeu.env, que todo o sistema lê ao iniciar (variáveis de ambiente
definidas na hora têm prioridade). Os dois arquivos ficam fora do git e só o dono lê (0600).
"""
import getpass
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import PROVIDERS, ROOT, SETTINGS_FILE

OWNER_FILE = Path(os.getenv("EMPORIO_OWNER", ROOT / "data" / "dono.json"))
MIN_PASSWORD = 8
LABELS = {"ollama": "IA local (Ollama, roda nesta máquina)", "openai": "ChatGPT (API da OpenAI)",
          "gemini": "Gemini (API do Google)", "anthropic": "Claude (API da Anthropic)"}


# ---------- login do dono ----------

def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def create_owner(user: str, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"a senha precisa ter pelo menos {MIN_PASSWORD} caracteres")
    salt = secrets.token_bytes(16)
    _write_private(OWNER_FILE, json.dumps({"usuario": user, "salt": salt.hex(), "hash": _hash(password, salt),
                                           "criado_em": datetime.now().isoformat(timespec="seconds")}))


def check_login(user: str, password: str) -> bool:
    data = json.loads(OWNER_FILE.read_text(encoding="utf-8"))
    expected = _hash(password, bytes.fromhex(data["salt"]))
    same_user = hmac.compare_digest(user.encode(), data["usuario"].encode())
    return same_user & hmac.compare_digest(expected.encode(), data["hash"].encode())


# ---------- configuração da IA ----------

def load_settings(path: Path = SETTINGS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
             if "=" in line and not line.lstrip().startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def save_settings(provider: str, model: str, api_key: str | None, mode: str) -> dict[str, str]:
    """Grava a escolha; a chave de outro provedor que já estava salva é mantida."""
    settings = load_settings()
    settings.update({"LLM_PROVIDER": provider, "LLM_MODEL": model, "EMPORIO_MODE": mode})
    key_env = PROVIDERS[provider]["key_env"]
    if key_env and api_key:
        settings[key_env] = api_key
    lines = ["# Gerado por `python -m emporio.setup`. Não versionar: contém chaves de API."]
    lines += [f"{k}={v}" for k, v in settings.items()]
    _write_private(SETTINGS_FILE, "\n".join(lines) + "\n")
    return settings


def mask(value: str) -> str:
    return "não definida" if not value else f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "definida"


# ---------- terminal ----------

def _ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def select(title: str, options: list[str], default: int = 0) -> int:
    """Menu com setas ↑/↓ e Enter; sem terminal interativo, cai para escolha por número."""
    try:
        import termios
        import tty
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except ImportError:  # Windows
        interactive = False
    if not interactive:
        for i, option in enumerate(options, 1):
            print(f"  {i}) {option}")
        answer = _ask(title, str(default + 1))
        return int(answer) - 1 if answer.isdigit() and 1 <= int(answer) <= len(options) else default

    index = default
    print(f"{title}  (↑/↓ e Enter)")

    def render(redraw: bool) -> None:
        if redraw:
            sys.stdout.write(f"\x1b[{len(options)}A")  # volta ao início da lista
        for i, option in enumerate(options):
            line = f"\x1b[1;36m❯ {option}\x1b[0m" if i == index else f"  {option}"
            sys.stdout.write(f"\x1b[2K{line}\n")
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    sys.stdout.write("\x1b[?25l")  # esconde o cursor
    render(False)
    try:
        tty.setcbreak(fd)
        while True:
            key = sys.stdin.read(1)
            if key in ("\n", "\r"):
                break
            if key == "\x1b" and sys.stdin.read(1) == "[":
                arrow = sys.stdin.read(1)
                index = (index - 1) % len(options) if arrow == "A" else (index + 1) % len(options) if arrow == "B" else index
            elif key in "kj":  # atalhos estilo vim
                index = (index - 1) % len(options) if key == "k" else (index + 1) % len(options)
            elif key.isdigit() and 1 <= int(key) <= len(options):
                index = int(key) - 1
            render(True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
    return index


def _login() -> bool:
    if not OWNER_FILE.exists():
        print("Primeiro acesso: crie o login do dono da loja.")
        user = _ask("Usuário")
        while True:
            password = getpass.getpass(f"Senha (mínimo {MIN_PASSWORD} caracteres): ")
            if password != getpass.getpass("Repita a senha: "):
                print("As senhas não conferem.")
                continue
            try:
                create_owner(user, password)
                print("Login criado.\n")
                return True
            except ValueError as exc:
                print(exc)
    for _ in range(3):
        if check_login(_ask("Usuário"), getpass.getpass("Senha: ")):
            print()
            return True
        print("Usuário ou senha incorretos.")
    return False


def _change_password() -> None:
    user = json.loads(OWNER_FILE.read_text(encoding="utf-8"))["usuario"]
    password = getpass.getpass(f"Nova senha (mínimo {MIN_PASSWORD} caracteres): ")
    if password != getpass.getpass("Repita a nova senha: "):
        print("As senhas não conferem; nada foi alterado.")
        return
    try:
        create_owner(user, password)  # sobrescreve: o login antigo vale até aqui
        print("Senha alterada.")
    except ValueError as exc:
        print(f"{exc}; nada foi alterado.")


def _ollama_models() -> list[str]:
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10).stdout
        names = [line.split()[0] for line in out.splitlines()[1:] if line.strip()]
        return [n for n in names if "embed" not in n]  # modelos de embedding não conversam
    except (OSError, subprocess.SubprocessError):
        return []


def _choose_ai(current: dict[str, str]) -> None:
    names = list(PROVIDERS)
    provider = names[select("Qual IA a loja vai usar?", [LABELS[n] for n in names],
                            names.index(current.get("LLM_PROVIDER", "ollama")))]
    previous_model = current.get("LLM_MODEL", "") if current.get("LLM_PROVIDER") == provider else ""

    api_key = None
    if provider == "ollama":
        models = _ollama_models()
        wanted = previous_model or PROVIDERS[provider]["model"]
        if models:
            options = models + ["outro (digitar o nome)"]
            choice = select("Qual modelo local?", options, models.index(wanted) if wanted in models else 0)
            model = models[choice] if choice < len(models) else _ask("Nome do modelo (ex.: qwen2.5:7b)")
        else:
            print("Nenhum modelo encontrado no Ollama (`ollama pull <modelo>` baixa um).")
            model = _ask("Modelo", wanted)
    else:
        key_env = PROVIDERS[provider]["key_env"]
        print(f"Chave atual: {mask(current.get(key_env, ''))}")
        api_key = getpass.getpass("Chave da API (Enter mantém a atual): ").strip() or None
        model = _ask("Modelo", previous_model or PROVIDERS[provider]["model"])
    modes = ["livre", "restrito"]
    suggested = current.get("EMPORIO_MODE") or ("livre" if provider != "ollama" else "restrito")
    mode = modes[select("Qual modo?", ["livre: o modelo escolhe as ferramentas (modelos maiores ou API)",
                                       "restrito: o código conduz e o modelo só preenche e redige (modelos pequenos)"],
                        modes.index(suggested) if suggested in modes else 0)]

    save_settings(provider, model, api_key, mode)
    print(f"\nSalvo em {SETTINGS_FILE}. Verificando o que falta...\n")
    # Processo novo: lê a configuração recém-gravada.
    if subprocess.call([sys.executable, "-m", "emporio.providers"]) != 0:
        if select("Instalar o que faltar agora?", ["sim", "não"]) == 0:
            subprocess.call([sys.executable, "-m", "emporio.providers", "--instalar"])


def main() -> None:
    print("Orfeu · configuração da loja\n")
    if not _login():
        raise SystemExit("Acesso negado.")
    while True:
        current = load_settings()
        provider = current.get("LLM_PROVIDER", "ollama")
        print(f"IA atual: {LABELS[provider]} · modelo {current.get('LLM_MODEL') or PROVIDERS[provider]['model'] or '?'}"
              f" · modo {current.get('EMPORIO_MODE', 'livre')}")
        choice = select("O que deseja fazer?", ["escolher a IA", "verificar a configuração", "trocar a senha", "sair"])
        if choice == 0:
            _choose_ai(current)
        elif choice == 1:
            subprocess.call([sys.executable, "-m", "emporio.providers"])
        elif choice == 2:
            _change_password()
        else:
            return
        print()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        # select() restaura o terminal no finally; aqui só não mostramos o traceback.
        print("\nSaindo. Nada foi alterado nesta etapa.")
        sys.exit(130)

"""Escolha do provedor do LLM e diagnóstico do que falta para ele funcionar.

    python -m emporio.providers                 # o provedor de LLM_PROVIDER
    python -m emporio.providers --todos         # todos
    python -m emporio.providers --instalar      # instala o pacote Python que faltar

Nada é instalado sem `--instalar`: o atendimento nunca baixa pacotes sozinho.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from urllib import request

from . import config


class ProviderError(RuntimeError):
    pass


def _settings(name: str) -> dict:
    p = config.PROVIDERS[name]
    current = name == config.LLM_PROVIDER
    return {
        "base_url": config.LLM_BASE_URL if current else p["base_url"],
        "model": config.LLM_MODEL if current else p["model"],
        "api_key": config.LLM_API_KEY if current else (os.getenv(p["key_env"] or "", "") or ""),
        **p,
    }


def problems(name: str = config.LLM_PROVIDER) -> list[str]:
    """O que impede o provedor de funcionar, com o comando para resolver cada item."""
    s = _settings(name)
    found = []
    if importlib.util.find_spec(s["package"]) is None:
        found.append(f"pacote Python `{s['package']}` não instalado: "
                     f"`pip install {s['package']}` ou `python -m emporio.providers --instalar`")
    if s["key_env"] and not s["api_key"]:
        found.append(f"chave não definida: `export {s['key_env']}=...`")
    if not s["model"]:
        found.append("modelo não definido: `export LLM_MODEL=...` (o nome do modelo no painel do provedor)")
    if name == "ollama":
        found += _ollama_problems(s)
    return found


def _ollama_problems(s: dict) -> list[str]:
    tags_url = s["base_url"].rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        with request.urlopen(tags_url, timeout=3) as resp:
            models = {m["name"] for m in json.loads(resp.read()).get("models", [])}
    except Exception:
        return [f"Ollama não responde em {tags_url}: instale em https://ollama.com e rode `ollama serve`"]
    wanted = s["model"] if ":" in s["model"] else f"{s['model']}:latest"
    if s["model"] and wanted not in models:
        return [f"modelo `{s['model']}` não baixado no Ollama: `ollama pull {s['model']}`"]
    return []


def install(name: str = config.LLM_PROVIDER) -> bool:
    package = config.PROVIDERS[name]["package"]
    if importlib.util.find_spec(package) is not None:
        return True
    print(f"Instalando {package}...")
    return subprocess.call([sys.executable, "-m", "pip", "install", package]) == 0


def make_client():
    """Cliente com a interface `chat.completions.create`, qualquer que seja o provedor."""
    s = _settings(config.LLM_PROVIDER)
    if importlib.util.find_spec(s["package"]) is None:
        raise ProviderError(f"Provedor {config.LLM_PROVIDER!r} precisa do pacote `{s['package']}`. "
                            "Rode `python -m emporio.providers` para ver o que falta.")
    if config.LLM_PROVIDER == "anthropic":
        import anthropic

        from .anthropic_adapter import AnthropicChat
        return AnthropicChat(anthropic.Anthropic(api_key=s["api_key"] or None), effort=config.LLM_EFFORT)
    from openai import OpenAI
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"] or "sem-chave")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico do provedor de LLM")
    parser.add_argument("--todos", action="store_true", help="verifica todos os provedores")
    parser.add_argument("--instalar", action="store_true", help="instala o pacote Python que faltar")
    args = parser.parse_args()
    names = list(config.PROVIDERS) if args.todos else [config.LLM_PROVIDER]
    ok_all = True
    for name in names:
        if args.instalar:
            install(name)
        found = problems(name)
        mark = "pronto" if not found else "falta configurar"
        current = " (atual)" if name == config.LLM_PROVIDER else ""
        print(f"{'✅' if not found else '⚠️ '} {name}{current}: {mark}")
        for item in found:
            print(f"   - {item}")
        ok_all &= not found
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
        sys.exit(130)

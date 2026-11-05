"""Chat no terminal. --telefone simula o número de quem manda a mensagem no WhatsApp.

Ctrl+C enquanto a Lira responde cancela só aquela resposta; Ctrl+C no prompt (ou /sair) encerra.
"""
import argparse
import hashlib
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, prompts, providers
from .agent import Agent

COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")
HELP = "/ajuda mostra os comandos · /limpar apaga o histórico desta conversa · /sair (ou Ctrl+C) encerra"


def paint(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if COLOR else text


def prompt_hash() -> str:
    text = prompts.SYSTEM_PROMPT + prompts.WRITER_PROMPT
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class Typing:
    """"Lira está digitando… N s" numa linha só, enquanto a resposta não chega."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if self.enabled:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self):
        start = time.monotonic()
        while not self._stop.wait(0.5):
            with self.lock:
                sys.stderr.write(f"\r\x1b[2K{paint(f'  Lira está digitando… {time.monotonic() - start:.0f} s', '2')}")
                sys.stderr.flush()

    def note(self, line: str) -> None:
        """Escreve uma linha (ex.: ferramenta chamada) sem atropelar o contador."""
        with self.lock:
            sys.stderr.write(f"\r\x1b[2K{line}\n")
            sys.stderr.flush()

    def __exit__(self, *_):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stderr.write("\r\x1b[2K")
            sys.stderr.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lira, assistente virtual da Empório da Música (ecossistema Orfeu)")
    parser.add_argument("--telefone", help="número do cliente, como se a conversa viesse do WhatsApp")
    parser.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas e o tempo")
    parser.add_argument("--roteiro", type=Path, help="arquivo com uma mensagem do cliente por linha")
    parser.add_argument("--saida", type=Path, help="salva a conversa em Markdown")
    parser.add_argument("--sessao", help="id de sessão (padrão: o telefone, ou anônima)")
    parser.add_argument("--modo", choices=["livre", "restrito"], help="padrão: EMPORIO_MODE ou livre")
    args = parser.parse_args()

    transcript: list[str] = []
    typing = Typing(enabled=sys.stderr.isatty() and not args.roteiro)

    def on_tool(name, tool_args, result):
        line = f"🔧 {name}({', '.join(f'{k}={v!r}' for k, v in tool_args.items())})"
        transcript.append(f"> {line}")
        if args.debug:
            typing.note(paint(f"  {line}", "2"))

    try:
        agent = Agent(phone=args.telefone, session_id=args.sessao, on_tool=on_tool, mode=args.modo)
    except providers.ProviderError as exc:
        raise SystemExit(f"⚠️  {exc}")
    who = agent.customer["name"] if agent.customer else "cliente não identificado"
    print(paint("Lira · Empório da Música", "1;36") + paint(f"  (ecossistema Orfeu)", "2"))
    print(paint(f"IA: {config.LLM_PROVIDER} · {config.LLM_MODEL} · modo {agent.mode} · {who}", "2"))
    if not args.roteiro:
        print(paint(HELP, "2"))
    print()

    lines = args.roteiro.read_text(encoding="utf-8").splitlines() if args.roteiro else None
    you, lira = paint("Você:", "1;34"), paint("Lira:", "1;35")
    while True:
        if lines is not None:
            if not lines:
                break
            text = lines.pop(0).strip()
            if not text:
                continue
            print(f"{you} {text}")
        else:
            try:
                text = input(f"{you} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        command = text.lower()
        if command in {"sair", "/sair", "exit", "quit"}:
            break
        if command == "/ajuda":
            print(paint(HELP, "2") + "\n")
            continue
        if command == "/limpar":
            agent.tools.conn.execute("DELETE FROM messages WHERE session_id = ?", (agent.session_id,))
            agent.tools.conn.commit()
            print(paint("Histórico desta conversa apagado.", "2") + "\n")
            continue
        if not text:
            continue

        mark = len(transcript)
        transcript.append(f"**Cliente:** {text}\n")
        try:
            with typing:
                answer = agent.reply(text)
        except KeyboardInterrupt:
            # Nada foi salvo: o histórico só grava a troca completa.
            del transcript[mark:]
            print(paint("  (resposta cancelada; Ctrl+C de novo no prompt encerra)", "2") + "\n")
            continue
        stats = agent.last_stats
        flags = [f"{stats['segundos']} s"]
        if stats.get("validador"):
            flags.append("validador barrou: " + ", ".join(stats["validador"]))
        if stats.get("resposta_segura"):
            flags.append("resposta segura")
        transcript.append(f"\n**Lira:** {answer}\n\n<sub>{' · '.join(flags)}</sub>\n")
        print(f"{lira} {answer}\n")
        if args.debug:
            print(paint(f"  [{' · '.join(flags)}]", "2"), file=sys.stderr)

    if not args.roteiro:
        print(paint("Até mais! 🎸", "2"))
    if args.saida:
        header = [f"# {args.saida.stem}", "",
                  f"- Cliente: {who}" + (f" (WhatsApp {args.telefone})" if args.telefone else ""),
                  f"- Modelo: `{config.LLM_MODEL}` · modo `{agent.mode}` · temperatura {config.LLM_TEMPERATURE:g} · "
                  f"prompt `{prompt_hash()}`",
                  f"- Gerado em {datetime.now():%d/%m/%Y %H:%M}; linhas com 🔧 são as ferramentas chamadas pelo agente.",
                  "", "---", ""]
        args.saida.write_text("\n".join(header + transcript) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

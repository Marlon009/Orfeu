"""Chat no terminal. --telefone simula o número de quem manda a mensagem no WhatsApp."""
import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

from . import config, prompts
from .agent import Agent


def prompt_hash() -> str:
    text = prompts.SYSTEM_PROMPT + prompts.WRITER_PROMPT
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description="Orfeu, assistente virtual da Empório da Música")
    parser.add_argument("--telefone", help="número do cliente, como se a conversa viesse do WhatsApp")
    parser.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    parser.add_argument("--roteiro", type=Path, help="arquivo com uma mensagem do cliente por linha")
    parser.add_argument("--saida", type=Path, help="salva a conversa em Markdown")
    parser.add_argument("--sessao", help="id de sessão (padrão: o telefone, ou anônima)")
    parser.add_argument("--modo", choices=["livre", "restrito"], help="padrão: EMPORIO_MODE ou livre")
    args = parser.parse_args()

    transcript: list[str] = []

    def on_tool(name, tool_args, result):
        line = f"🔧 {name}({', '.join(f'{k}={v!r}' for k, v in tool_args.items())})"
        transcript.append(f"> {line}")
        if args.debug:
            print(f"  {line}", file=sys.stderr)

    agent = Agent(phone=args.telefone, session_id=args.sessao, on_tool=on_tool, mode=args.modo)
    who = agent.customer["name"] if agent.customer else "cliente não identificado"
    print(f"Empório da Música — atendimento virtual ({who}). Digite 'sair' para encerrar.\n")

    lines = args.roteiro.read_text(encoding="utf-8").splitlines() if args.roteiro else None
    while True:
        if lines is not None:
            if not lines:
                break
            text = lines.pop(0).strip()
            if not text:
                continue
            print(f"Você: {text}")
        else:
            try:
                text = input("Você: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
        if text.lower() in {"sair", "exit", "quit"}:
            break
        if not text:
            continue
        transcript.append(f"**Cliente:** {text}\n")
        answer = agent.reply(text)
        stats = agent.last_stats
        flags = [f"{stats['segundos']} s"]
        if stats.get("validador"):
            flags.append("validador barrou: " + ", ".join(stats["validador"]))
        if stats.get("resposta_segura"):
            flags.append("resposta segura")
        transcript.append(f"\n**Orfeu:** {answer}\n\n<sub>{' · '.join(flags)}</sub>\n")
        print(f"Orfeu: {answer}\n")
        if args.debug:
            print(f"  [{' · '.join(flags)}]", file=sys.stderr)

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

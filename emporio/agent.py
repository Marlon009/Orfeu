"""Agente sobre qualquer API compatível com a OpenAI (Ollama por padrão), em dois modos.

- livre: loop de function calling; o modelo decide quais ferramentas chamar e quando.
- restrito: o modelo só preenche um formulário JSON validado (`interpreter.py`), o código
  executa as ferramentas e o modelo apenas redige a resposta.

Nos dois modos a resposta passa pelo validador antes de sair.
"""
import ast
import json
import re
import sqlite3
import time
from collections.abc import Callable

from openai import OpenAI

from . import config
from .interpreter import Interpreter
from .prompts import WRITER_PROMPT, build_system_prompt, reminders
from .tools import Toolbox, tool_specs
from .validator import unsupported

MAX_STEPS = 5
FALLBACK = ("Desculpa, tive um probleminha aqui pra concluir sua solicitação. 😅 "
            "Pode falar com a nossa equipe pelo WhatsApp (67) 3321-4500, de segunda a sexta das 9h às 18h "
            "e sábado das 9h às 13h.")
ACCESSORY_REPLY = ("Esse a gente não tem: a Empório trabalha só com instrumentos musicais, sem acessórios "
                   "como cordas, palhetas, cabos ou pedais. Vale procurar uma loja especializada em acessórios. "
                   "Posso te ajudar com algum instrumento? 🎸")
OFF_TOPIC_REPLY = ("Essa eu fico devendo! 😄 Por aqui eu só ajudo com instrumentos musicais e com a loja: "
                   "produtos, pedidos, horários, pagamento e trocas. Quer ajuda com algum desses?")


def find_customer(conn: sqlite3.Connection, phone: str | None) -> sqlite3.Row | None:
    digits = "".join(c for c in phone or "" if c.isdigit())
    if len(digits) < 8:
        return None
    return conn.execute("SELECT * FROM customers WHERE phone_digits LIKE ?", (f"%{digits[-8:]}",)).fetchone()


class Agent:
    def __init__(self, phone: str | None = None, session_id: str | None = None,
                 on_tool: Callable[[str, dict, str], None] | None = None, client: OpenAI | None = None,
                 mode: str | None = None):
        self.tools = Toolbox(session_id or "anon")
        self.tools.customer = find_customer(self.tools.conn, phone)
        # Sessão = número do WhatsApp; assim o histórico volta quando o cliente retorna.
        self.session_id = session_id or (f"tel-{self.tools.customer['phone_digits']}" if self.tools.customer else "anon")
        self.tools.session_id = self.session_id
        self.client = client or OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        self.specs = tool_specs(self.tools.conn)
        self.params = {s["function"]["name"]: s["function"]["parameters"]["properties"] for s in self.specs}
        self.mode = mode or config.AGENT_MODE
        self.interpreter = Interpreter(self.specs)
        self.on_tool = on_tool
        self.last_stats: dict = {}

    @property
    def customer(self):
        return self.tools.customer

    def _history(self) -> list[dict]:
        rows = self.tools.conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.session_id, config.HISTORY_TURNS * 2)).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def _save(self, role: str, content: str) -> None:
        self.tools.conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                                (self.session_id, role, content))
        self.tools.conn.commit()

    def _chat(self, messages: list[dict], **kwargs):
        return self.client.chat.completions.create(
            model=config.LLM_MODEL, messages=messages, temperature=config.LLM_TEMPERATURE, **kwargs
        ).choices[0].message

    def _call_tool(self, name: str, raw_args: str | dict) -> str:
        if name not in self.params:
            return f"Ferramenta inexistente: {name}."
        args = {}
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            # Modelos pequenos às vezes mandam argumentos extras ou vazios.
            args = {k: v for k, v in (parsed or {}).items() if k in self.params[name] and v not in ("", None)}
            result = getattr(self.tools, name)(**args)
        except Exception as exc:  # o erro volta para o modelo tentar de novo
            result = f"Erro ao executar {name}: {exc}"
        self.tool_outputs.append(result)
        if self.on_tool:
            self.on_tool(name, args, result)
        return result

    def _calls_in_text(self, content: str) -> list[tuple[str, str, dict]]:
        """O Qwen às vezes escreve a chamada no texto (JSON ou `nome(arg=valor)`) em vez de usar tool_calls."""
        match = re.fullmatch(r"\s*(\w+)\((.*)\)\s*", content, re.DOTALL)
        if match and match[1] in self.params:
            try:
                call = ast.parse(f"f({match[2]})", mode="eval").body
                return [("text-call", match[1], {k.arg: ast.literal_eval(k.value) for k in call.keywords})]
            except (SyntaxError, ValueError):
                return []
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < start:
            return []
        try:
            data = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict) and data.get("name") in self.params:
            return [("text-call", data["name"], data.get("arguments") or {})]
        return []

    def _problems(self, answer: str, user_text: str, history: list[dict]) -> list[str]:
        return unsupported(answer, self.tool_outputs + [user_text] + [m["content"] for m in history])

    # ---------- modo livre ----------

    def _reply_free(self, user_text: str, history: list[dict]) -> str:
        messages = [{"role": "system", "content": build_system_prompt(self.tools.today, self.customer)}, *history]
        notes = reminders(user_text, self.customer)
        if notes:
            messages.append({"role": "system", "content": "Lembrete para esta mensagem: " + " ".join(notes)})
        messages.append({"role": "user", "content": user_text})
        retried = False
        for _ in range(MAX_STEPS):
            msg = self._chat(messages, tools=self.specs)
            calls = [(c.id, c.function.name, c.function.arguments) for c in msg.tool_calls or []]
            if not calls:
                calls = self._calls_in_text(msg.content or "")
            if not calls:
                answer = (msg.content or "").strip()
                problems = self._problems(answer, user_text, history)
                if not problems:
                    return answer
                self.last_stats["validador"] = problems
                if retried:
                    break
                retried = True
                # Dá ao modelo a chance de consultar a ferramenta que faltou.
                messages += [{"role": "assistant", "content": answer},
                             {"role": "system", "content": f"Sua resposta cita {', '.join(problems)}, que não "
                              "aparece nos dados consultados. Consulte a ferramenta certa ou responda sem esses valores."}]
                continue
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args) if isinstance(args, dict) else args}}
                for cid, name, args in calls]})
            for cid, name, args in calls:
                messages.append({"role": "tool", "tool_call_id": cid, "content": self._call_tool(name, args)})
        self.last_stats["resposta_segura"] = True
        return FALLBACK

    # ---------- modo restrito ----------

    def _reply_restricted(self, user_text: str, history: list[dict]) -> str:
        previous = [m["content"] for m in history if m["role"] == "user"][-2:]
        req = self.interpreter.request(user_text, previous)
        msg = self._chat(req["messages"], response_format=req["response_format"])
        try:
            data = self.interpreter.ground(msg.content or "{}", previous + [user_text])
        except (json.JSONDecodeError, TypeError, ValueError):
            data = {"intencoes": ["conversa"]}
        self.last_stats["intencao"] = data

        intents = set(data["intencoes"])
        calls = self.interpreter.calls(data)
        if not calls and intents & {"acessorio", "fora_de_escopo"}:
            return ACCESSORY_REPLY if "acessorio" in intents else OFF_TOPIC_REPLY

        for name, args in calls:
            if name == "registrar_reclamacao":
                args["descricao"] = user_text
            if name == "consultar_politica" and "topico" not in args:
                continue
            self._call_tool(name, args)
            if name == "buscar_produtos" and (args.get("termo") or args.get("categoria")):
                self.tools.registrar_interesse(args.get("termo") or args["categoria"], args.get("categoria"))

        notes = reminders(user_text, None)
        if "acessorio" in intents:
            notes.append("O cliente também pediu acessório: diga que a loja não vende acessórios.")
        data_block = "\n\n".join(self.tool_outputs) or "(nenhuma consulta: é só conversa)"
        messages = [{"role": "system", "content": WRITER_PROMPT.format(
                        customer=self.customer["name"].split()[0] if self.customer else "não identificado")},
                    # Só as mensagens do cliente: modelos pequenos copiam respostas anteriores.
                    *[m for m in history[-4:] if m["role"] == "user"],
                    {"role": "user", "content": f"{user_text}\n\n[DADOS CONSULTADOS]\n{data_block}"
                     + (f"\n\n[LEMBRETE] {' '.join(notes)}" if notes else "")}]
        for attempt in range(2):
            answer = (self._chat(messages).content or "").strip()
            problems = self._problems(answer, user_text, history)
            if not problems:
                return answer
            self.last_stats["validador"] = problems
            messages += [{"role": "assistant", "content": answer},
                         {"role": "system", "content": f"Você citou {', '.join(problems)}, que não está nos DADOS "
                          "CONSULTADOS. Reescreva usando só os valores dos dados."}]
        self.last_stats["resposta_segura"] = True
        return FALLBACK

    def reply(self, user_text: str) -> str:
        start = time.monotonic()
        self.tool_outputs: list[str] = []
        self.last_stats = {"modo": self.mode}
        history = self._history()
        if self.mode == "restrito":
            answer = self._reply_restricted(user_text, history)
        else:
            answer = self._reply_free(user_text, history)
        self.last_stats["segundos"] = round(time.monotonic() - start)
        self._save("user", user_text)
        self._save("assistant", answer)
        return answer

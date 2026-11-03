"""Loop de function calling sobre qualquer API compatível com a OpenAI (Ollama por padrão)."""
import json
import sqlite3
from collections.abc import Callable

from openai import OpenAI

from . import config
from .prompts import build_system_prompt, reminders
from .tools import Toolbox, tool_specs

MAX_STEPS = 5
FALLBACK = ("Desculpa, tive um probleminha aqui pra concluir sua solicitação. 😅 "
            "Pode falar com a nossa equipe pelo WhatsApp (67) 3321-4500, de segunda a sexta das 9h às 18h "
            "e sábado das 9h às 13h.")


def find_customer(conn: sqlite3.Connection, phone: str | None) -> sqlite3.Row | None:
    digits = "".join(c for c in phone or "" if c.isdigit())
    if len(digits) < 8:
        return None
    return conn.execute("SELECT * FROM customers WHERE phone_digits LIKE ?", (f"%{digits[-8:]}",)).fetchone()


class Agent:
    def __init__(self, phone: str | None = None, session_id: str | None = None,
                 on_tool: Callable[[str, dict, str], None] | None = None, client: OpenAI | None = None):
        self.tools = Toolbox(session_id or "anon")
        self.tools.customer = find_customer(self.tools.conn, phone)
        # Sessão = número do WhatsApp; assim o histórico volta quando o cliente retorna.
        self.session_id = session_id or (f"tel-{self.tools.customer['phone_digits']}" if self.tools.customer else "anon")
        self.tools.session_id = self.session_id
        self.client = client or OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        self.specs = tool_specs(self.tools.conn)
        self.params = {s["function"]["name"]: s["function"]["parameters"]["properties"] for s in self.specs}
        self.on_tool = on_tool

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
        if self.on_tool:
            self.on_tool(name, args, result)
        return result

    def reply(self, user_text: str) -> str:
        messages = [{"role": "system", "content": build_system_prompt(self.tools.today, self.customer)},
                    *self._history()]
        notes = reminders(user_text, self.customer)
        if notes:
            messages.append({"role": "system", "content": "Lembrete para esta mensagem: " + " ".join(notes)})
        messages.append({"role": "user", "content": user_text})
        answer = None
        for _ in range(MAX_STEPS):
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL, messages=messages, tools=self.specs,
                temperature=config.LLM_TEMPERATURE)
            msg = response.choices[0].message
            if not msg.tool_calls:
                answer = (msg.content or "").strip()
                break
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [c.model_dump() for c in msg.tool_calls]})
            for call in msg.tool_calls:
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": self._call_tool(call.function.name, call.function.arguments)})
        answer = answer or FALLBACK
        self._save("user", user_text)
        self._save("assistant", answer)
        return answer

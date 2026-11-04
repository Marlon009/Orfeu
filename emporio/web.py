"""Servidor HTTP: página de chat, API JSON e webhook do WhatsApp, todos sobre o mesmo Agent.

    python -m emporio.web          # http://127.0.0.1:8000

A sessão de quem é identificado pelo telefone é a mesma em qualquer canal (`tel-<dígitos>`),
então uma conversa começada no WhatsApp continua na web e no terminal.
"""
import os
import re
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import whatsapp
from .agent import Agent, find_customer
from .db import connect

STATIC = Path(__file__).parent / "static"
PUBLIC_URL = os.getenv("PUBLIC_URL", "")  # URL pública do webhook (ngrok), usada na assinatura do Twilio

app = FastAPI(title="Lia — Empório da Música")


class Message(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    sessao: str = Field(default="", max_length=64)
    telefone: str = Field(default="", max_length=30)


def _session_for(telefone: str, fallback: str) -> str | None:
    """None deixa o Agent usar a sessão do telefone (cliente identificado)."""
    if find_customer(connect(), telefone):
        return None
    return fallback


def _web_session(sessao: str) -> str:
    return "web-" + (re.sub(r"[^A-Za-z0-9-]", "", sessao) or "anon")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/api/mensagem")
def mensagem(msg: Message) -> dict:
    # Rota síncrona: o FastAPI a executa num thread à parte, e o Agent abre a própria conexão.
    tools_used = []
    agent = Agent(phone=msg.telefone, session_id=_session_for(msg.telefone, _web_session(msg.sessao)),
                  on_tool=lambda name, args, result: tools_used.append({"nome": name, "args": args}))
    answer = agent.reply(msg.texto.strip())
    stats = agent.last_stats
    return {"resposta": answer, "ferramentas": tools_used, "segundos": stats.get("segundos"),
            "validador": stats.get("validador", []), "resposta_segura": bool(stats.get("resposta_segura")),
            "modo": stats.get("modo"), "cliente": agent.customer["name"] if agent.customer else None}


@app.get("/api/historico")
def historico(sessao: str = "", telefone: str = "") -> dict:
    session = _session_for(telefone, _web_session(sessao))
    agent = Agent(phone=telefone, session_id=session, client=object())
    rows = agent.tools.conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (agent.session_id,)).fetchall()
    return {"cliente": agent.customer["name"] if agent.customer else None,
            "mensagens": [{"papel": r["role"], "texto": r["content"]} for r in rows]}


def _answer_whatsapp(phone: str, text: str) -> None:
    digits = "".join(c for c in phone if c.isdigit())
    agent = Agent(phone=phone, session_id=_session_for(phone, f"wa-{digits}"))
    whatsapp.send(phone, agent.reply(text))


@app.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request, background: BackgroundTasks) -> Response:
    incoming = whatsapp.parse_incoming(await request.body())
    if whatsapp.AUTH_TOKEN:
        url = PUBLIC_URL.rstrip("/") + request.url.path if PUBLIC_URL else str(request.url)
        if not whatsapp.valid_signature(url, incoming["params"], request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403, detail="assinatura inválida")
    if incoming["telefone"] and incoming["texto"]:
        background.add_task(_answer_whatsapp, incoming["telefone"], incoming["texto"])
    # Confirma na hora com TwiML vazio; a resposta vai depois pela API REST.
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type="application/xml")


@app.get("/api/whatsapp/saida")
def whatsapp_saida() -> list[dict]:
    """Caixa de saída do modo simulado, para demonstração. Desligada quando há credenciais reais."""
    if whatsapp.ACCOUNT_SID:
        raise HTTPException(status_code=404)
    rows = connect().execute(
        "SELECT recipient, body, status, created_at FROM outbound_messages ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()

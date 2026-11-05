from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from emporio import providers, web, whatsapp
from emporio.db import connect


class EchoClient:
    """LLM falso: responde uma saudação fixa, sem números (passa no validador)."""

    def __init__(self, *_, **__):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_):
        message = SimpleNamespace(content="Oi! Como posso te ajudar?", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(providers, "make_client", EchoClient)
    return TestClient(web.app)


def test_page_is_served(client):
    assert "Lira · Empório da Música" in client.get("/").text


def test_chat_and_history(client):
    out = client.post("/api/mensagem", json={"texto": "oi", "sessao": "teste-web"}).json()
    assert out["resposta"] == "Oi! Como posso te ajudar?" and out["cliente"] is None
    history = client.get("/api/historico", params={"sessao": "teste-web"}).json()["mensagens"]
    assert [m["papel"] for m in history[-2:]] == ["user", "assistant"]


def test_phone_identifies_customer_across_channels(client):
    out = client.post("/api/mensagem", json={"texto": "oi", "sessao": "x", "telefone": "(67) 99654-7821"}).json()
    assert out["cliente"] == "Ana Carolina Ferreira"
    # Mesma sessão tel-... do WhatsApp e do terminal, independente do id do navegador.
    other_browser = client.get("/api/historico", params={"sessao": "outro", "telefone": "67996547821"}).json()
    assert other_browser["mensagens"]


def test_empty_message_is_rejected(client):
    assert client.post("/api/mensagem", json={"texto": ""}).status_code == 422


def test_whatsapp_webhook_answers_in_background(client):
    form = urlencode({"From": "whatsapp:+5511900001111", "Body": "Oi, tudo bem?"})
    res = client.post("/webhook/whatsapp", content=form,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert res.status_code == 200 and "<Response/>" in res.text
    # O TestClient executa a tarefa de fundo antes de devolver; sem credenciais, o envio é simulado.
    last = client.get("/api/whatsapp/saida").json()[0]
    assert last["recipient"] == "+5511900001111" and last["status"] == "simulado"
    sessions = {r["session_id"] for r in connect().execute("SELECT DISTINCT session_id FROM messages")}
    assert "wa-5511900001111" in sessions  # desconhecido não cai na sessão "anon" compartilhada


def test_whatsapp_signature(client, monkeypatch):
    monkeypatch.setattr(whatsapp, "AUTH_TOKEN", "segredo")
    params = {"From": "whatsapp:+5511900001111", "Body": "Oi"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    bad = client.post("/webhook/whatsapp", content=urlencode(params), headers={**headers, "X-Twilio-Signature": "x"})
    assert bad.status_code == 403
    signature = whatsapp.signature_for("http://testserver/webhook/whatsapp", params, "segredo")
    ok = client.post("/webhook/whatsapp", content=urlencode(params), headers={**headers, "X-Twilio-Signature": signature})
    assert ok.status_code == 200


def test_long_answer_is_split():
    text = "\n".join(["linha " + "x" * 100] * 30)
    chunks = whatsapp._chunks(text)
    assert len(chunks) > 1 and all(len(c) <= whatsapp.MAX_BODY for c in chunks)

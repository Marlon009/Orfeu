"""Adaptador do WhatsApp via Twilio: ler a mensagem recebida, validar a assinatura e enviar a resposta.

O agente leva de segundos a minutos para responder, e o Twilio espera o webhook responder
em até 15 s. Por isso o webhook só confirma o recebimento; a resposta sai depois pela API
REST. Sem credenciais (TWILIO_*), nada é enviado: a resposta fica em `outbound_messages`
com status "simulado", o que permite testar o fluxo inteiro sem conta.
"""
import base64
import hashlib
import hmac
import json
import os
from urllib import parse, request

from .db import connect

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM", "")  # ex.: whatsapp:+14155238886 (sandbox)
MAX_BODY = 1500  # o WhatsApp via Twilio corta mensagens acima de 1600 caracteres


def parse_incoming(body: bytes) -> dict[str, str]:
    """O Twilio manda application/x-www-form-urlencoded; só interessam From e Body."""
    form = {k: v[0] for k, v in parse.parse_qs(body.decode("utf-8")).items()}
    return {"telefone": form.get("From", "").removeprefix("whatsapp:"), "texto": form.get("Body", "").strip(),
            "params": form}


def signature_for(url: str, params: dict[str, str], token: str) -> str:
    """Algoritmo do Twilio: HMAC-SHA1 da URL seguida dos parâmetros ordenados, em base64."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def valid_signature(url: str, params: dict[str, str], signature: str) -> bool:
    return hmac.compare_digest(signature_for(url, params, AUTH_TOKEN), signature or "")


def _chunks(text: str) -> list[str]:
    parts, current = [], ""
    for paragraph in text.split("\n"):
        if current and len(current) + len(paragraph) + 1 > MAX_BODY:
            parts.append(current)
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
    return parts + [current] if current else parts


def send(to: str, text: str) -> str:
    """Envia pela API do Twilio, ou só registra se não houver credenciais. Devolve o status."""
    conn = connect()
    status = "simulado"
    for chunk in _chunks(text):
        if ACCOUNT_SID and AUTH_TOKEN and FROM_NUMBER:
            data = parse.urlencode({"From": FROM_NUMBER, "To": f"whatsapp:{to}", "Body": chunk}).encode()
            req = request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json", data=data)
            req.add_header("Authorization", "Basic " + base64.b64encode(f"{ACCOUNT_SID}:{AUTH_TOKEN}".encode()).decode())
            try:
                with request.urlopen(req, timeout=20) as resp:
                    status = json.loads(resp.read()).get("status", "enviado")
            except Exception as exc:  # falha de envio fica registrada, não derruba o atendimento
                status = f"erro: {exc}"
        conn.execute("INSERT INTO outbound_messages (channel, recipient, body, status) VALUES ('whatsapp', ?, ?, ?)",
                     (to, chunk, status))
    conn.commit()
    return status

from types import SimpleNamespace

from emporio.agent import FALLBACK, OFF_TOPIC_REPLY, Agent


class FakeClient:
    """Devolve as respostas na ordem e guarda o que recebeu."""

    def __init__(self, *contents):
        self.contents = list(contents)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self.contents.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def agent_with(*contents, session="t-restrito", phone=None):
    client = FakeClient(*contents)
    calls = []
    agent = Agent(phone=phone, session_id=session, client=client, mode="restrito",
                  on_tool=lambda name, args, result: calls.append((name, args)))
    agent.tools.conn.execute("DELETE FROM messages WHERE session_id = ?", (session,))
    agent.tools.conn.commit()
    return agent, client, calls


def test_schema_comes_from_tool_registry():
    agent, *_ = agent_with()
    schema = agent.interpreter.schema
    intents = schema["properties"]["intencoes"]["items"]["enum"]
    assert {"buscar_produtos", "consultar_pedido", "consultar_politica", "fora_de_escopo"} <= set(intents)
    assert "registrar_interesse" not in intents  # automático no modo restrito
    assert "Violões" in schema["properties"]["categoria"]["enum"]


def test_price_question_runs_tool_and_validates():
    agent, client, calls = agent_with(
        '{"intencoes": ["buscar_produtos"], "termo": "Takamine GD20"}',
        "O Takamine GD20 sai por R$ 2.199,00, ou R$ 2.089,05 no PIX!")
    answer = agent.reply("Quanto custa o Takamine GD20?")
    assert calls[0] == ("buscar_produtos", {"termo": "Takamine GD20"})
    assert "R$ 2.199,00" in answer and "validador" not in agent.last_stats
    assert client.requests[0]["response_format"]["type"] == "json_schema"


def test_invented_price_is_retried_then_blocked():
    agent, _, _ = agent_with(
        '{"intencoes": ["buscar_produtos"], "termo": "Takamine GD20"}',
        "Sai por R$ 1.500,00!", "Sai por R$ 1.400,00!")
    assert agent.reply("Quanto custa o Takamine GD20?") == FALLBACK
    assert agent.last_stats["resposta_segura"]


def test_off_topic_needs_no_second_call():
    agent, client, calls = agent_with('{"intencoes": ["fora_de_escopo"]}')
    assert agent.reply("me passa uma receita de bolo") == OFF_TOPIC_REPLY
    assert len(client.requests) == 1 and not calls


def test_invented_order_number_and_contact_are_dropped():
    agent, _, calls = agent_with(
        '{"intencoes": ["consultar_pedido"], "numero_pedido": 12345, "email_ou_telefone": "x@y.com"}',
        "Me passa o número do pedido e o e-mail do cadastro?")
    agent.reply("Me arrependi da compra, posso devolver?")
    assert calls[0] == ("consultar_pedido", {})


def test_grounded_order_lookup():
    agent, _, calls = agent_with(
        '{"intencoes": ["consultar_pedido"], "numero_pedido": 7, "email_ou_telefone": "leticia.rocha@jmail.com"}',
        "O prazo de devolução encerrou em 24/02/2026, mas a garantia legal vale até 18/05/2026.")
    answer = agent.reply("É o pedido 7, meu e-mail é leticia.rocha@jmail.com")
    assert calls[0] == ("consultar_pedido", {"numero_pedido": 7, "email_ou_telefone": "leticia.rocha@jmail.com"})
    assert "validador" not in agent.last_stats and "18/05/2026" in answer


def test_ungrounded_accessory_becomes_product_search():
    agent, *_ = agent_with()
    data = agent.interpreter.ground('{"intencoes": ["acessorio"]}', ["Vocês têm violão de 7 cordas?"])
    assert data["intencoes"] == ["buscar_produtos"] and data["categoria"] == "Violões"
    data = agent.interpreter.ground('{"intencoes": ["acessorio"]}', ["tem jogo de cordas pro violão?"])
    assert data["intencoes"] == ["acessorio"]


def test_price_in_thousands_is_grounded():
    from emporio.interpreter import numbers_in
    agent, *_ = agent_with()
    data = agent.interpreter.ground('{"intencoes": ["buscar_produtos"], "preco_max": 9000}', ["baixo até 9 mil reais"])
    assert data["preco_max"] == 9000
    assert numbers_in("R$ 1.500 ou 2.199,90 ou 799.90") == [1500, 2199.9, 799.9]

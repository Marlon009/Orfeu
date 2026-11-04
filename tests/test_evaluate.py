from emporio.evaluate import score

INTENTS = ["buscar_produtos", "consultar_pedido", "consultar_politica", "registrar_reclamacao",
           "acessorio", "fora_de_escopo", "conversa"]


def case(**kw):
    return {"id": "x", "grupo": "g", **kw}


def test_correct_output_passes():
    out = {"intencoes": ["buscar_produtos"], "termo": "Takamine GD20 Dreadnought"}
    assert score(case(intencoes=["buscar_produtos"], campos={"termo": "takamine gd20"}), out, out, INTENTS)["ok"]


def test_refusing_a_store_question_fails():
    out = {"intencoes": ["buscar_produtos", "fora_de_escopo"]}
    result = score(case(intencoes=["buscar_produtos"]), out, out, INTENTS)
    assert not result["ok"] and "proibida" in result["problemas"][0]


def test_refusal_that_calls_a_tool_fails():
    out = {"intencoes": ["fora_de_escopo", "buscar_produtos"]}
    assert not score(case(intencoes=["fora_de_escopo"]), out, out, INTENTS)["ok"]


def test_extra_tool_intent_is_allowed():
    out = {"intencoes": ["consultar_pedido", "consultar_politica"], "topico": "trocas_devolucoes"}
    assert score(case(intencoes=["consultar_pedido"]), out, out, INTENTS)["ok"]


def test_invented_field_fails_and_dropped_field_is_counted():
    raw = {"intencoes": ["consultar_pedido"], "numero_pedido": 12345}
    grounded = {"intencoes": ["consultar_pedido"]}
    result = score(case(intencoes=["consultar_pedido"], sem_campos=["numero_pedido"]), raw, grounded, INTENTS)
    assert result["ok"] and result["descartados"] == ["numero_pedido"]
    assert not score(case(intencoes=["consultar_pedido"], sem_campos=["numero_pedido"]), raw, raw, INTENTS)["ok"]


def test_numeric_and_contact_fields():
    out = {"intencoes": ["consultar_pedido"], "numero_pedido": 8, "email_ou_telefone": "67 99654-7821"}
    c = case(intencoes=["consultar_pedido"], campos={"numero_pedido": 8, "email_ou_telefone": "(67) 99654-7821"})
    assert score(c, out, out, INTENTS)["ok"]

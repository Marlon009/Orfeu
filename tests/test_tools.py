from datetime import date

import pytest

from emporio import rules
from emporio.tools import Toolbox


@pytest.fixture(scope="module")
def tools():
    return Toolbox("pytest", today=date(2026, 3, 25))


def test_brl():
    assert rules.brl(2089.05) == "R$ 2.089,05"


@pytest.mark.parametrize("value, expected", [(40, 1), (150, 3), (429.9, 5), (599.9, 6), (749, 7), (2199, 12)])
def test_max_installments_respects_minimum(value, expected):
    assert rules.max_installments(value) == expected


def test_pix_does_not_stack_with_promotion():
    promo = rules.price_for(2399, 18, "Desconto Exclusivo")
    assert promo.final == pytest.approx(1967.18) and promo.pix is None
    assert rules.price_for(2199).pix == pytest.approx(2089.05)


def test_price_lookup(tools):
    out = tools.buscar_produtos(termo="Takamine GD20")
    assert "R$ 2.199,00" in out and "R$ 2.089,05" in out


def test_only_active_promotion_is_applied(tools):
    # Produto 96 tem duas promoções, ambas inativas, e está sem estoque.
    out = tools.buscar_produtos(termo="Giannini GF-3D")
    assert "off, promoção" not in out.split("Alternativas")[0]
    assert "ESGOTADO" in out and "Alternativas disponíveis" in out


def test_budget_listing_excludes_unavailable(tools):
    out = tools.buscar_produtos(categoria="Violões", preco_max=1000)
    assert "Giannini GF-3D" not in out and "Shelby SN-7C" not in out


def test_discontinued_product_has_no_price(tools):
    out = tools.buscar_produtos(termo="Ibanez Bass 2X").split("Alternativas")[0]
    assert "DESCONTINUADO" in out and "Preço" not in out


def test_unreliable_description_is_hidden(tools):
    out = tools.buscar_produtos(termo="Music Man Bass 1X")
    assert "Fender" not in out


def test_order_requires_identity(tools):
    assert "Não foi possível confirmar" in tools.consultar_pedido(4, "outra@pessoa.com")
    assert "Não foi possível confirmar" in tools.consultar_pedido(999, "lucas.mendes@jmail.com")
    assert "Giannini GF-3D" in tools.consultar_pedido(4, "LUCAS.MENDES@jmail.com")
    assert "Giannini GF-3D" in tools.consultar_pedido(4, "67 99812-3456")


def test_return_window(tools):
    out = tools.consultar_pedido(7, "leticia.rocha@jmail.com")  # entregue em 17/02/2026
    assert "Arrependimento/devolução (7 dias após o recebimento, compras online): FORA" in out
    assert "Garantia legal (90 dias após o recebimento): DENTRO" in out
    assert "CONCLUSÃO: Ainda vale: garantia legal contra defeito." in out


def test_late_shipment_opens_single_complaint(tools):
    first = tools.consultar_pedido(8, "anacarol.ferreira@coldmail.com")
    second = tools.consultar_pedido(8, "anacarol.ferreira@coldmail.com")
    assert "ATRASADO" in first and "protocolo nº 1" in first and "protocolo nº 1" in second


def test_policy_topic_fallback(tools):
    assert "Trocas e devoluções" in tools.consultar_politica("trocas")


def test_search_ignores_wrong_category(tools):
    assert "Giannini GF-3D" in tools.buscar_produtos(termo="Giannini GF-3D", categoria="Guitarras")


def test_hours_live_in_store_topic(tools):
    assert "Sábado: 09:00 às 13:00" in tools.consultar_politica("horario")


def test_reminders():
    from emporio.prompts import reminders
    assert any("ACESSÓRIO" in n for n in reminders("Vocês vendem cordas de violão?"))
    assert not reminders("O estoque acabou? Seria capaz de ver um violão de 7 cordas?")
    assert any("receita" not in n and "recuse" in n for n in reminders("me passa uma receita"))
    assert reminders("cadê meu pedido?", customer={"name": "Ana"}) and not reminders("cadê meu pedido?")


def test_tool_call_written_as_text():
    from emporio.agent import Agent
    agent = Agent(client=object())
    calls = agent._calls_in_text('Ronaldo\n{"name": "buscar_produtos", "arguments": {"preco_max": 1000}}')
    assert calls == [("text-call", "buscar_produtos", {"preco_max": 1000})]
    assert agent._calls_in_text("consultar_pedido()") == [("text-call", "consultar_pedido", {})]
    assert agent._calls_in_text("consultar_pedido(numero_pedido=7)") == [("text-call", "consultar_pedido", {"numero_pedido": 7})]
    assert agent._calls_in_text("Olá! Tudo bem?") == []
    assert agent._calls_in_text("Veja (isso)") == []


def test_generic_search_hides_unavailable(tools):
    out = tools.buscar_produtos(termo="nylon", categoria="Violões", preco_max=1000)
    assert "Shelby SN-7C" not in out and "Yamaha C40" in out
    assert "DESCONTINUADO" in tools.buscar_produtos(termo="Shelby SN-7C")


@pytest.mark.parametrize("when, expected", [
    ("2026-03-25T10:00", "ABERTA agora (fecha às 18:00)"),             # quarta de manhã
    ("2026-03-25T19:30", "volta amanhã (26/03/2026) às 09:00"),         # quarta à noite
    ("2026-03-28T14:00", "volta segunda (30/03/2026) às 09:00"),        # sábado depois das 13h
    ("2026-03-29T11:00", "volta amanhã (30/03/2026) às 09:00"),         # domingo
    ("2026-03-27T07:45", "volta hoje (27/03/2026) às 09:00"),           # sexta antes de abrir
    ("2026-03-28T12:59", "ABERTA agora (fecha às 13:00)"),              # sábado quase fechando
])
def test_store_status(when, expected):
    from datetime import datetime
    assert expected in rules.store_status(datetime.fromisoformat(when))


def test_store_hours_in_prompt_and_allowed_by_validator(monkeypatch):
    from emporio.prompts import build_system_prompt
    from emporio.validator import unsupported
    from datetime import datetime
    status = rules.store_status(datetime.fromisoformat("2026-03-28T14:00"))
    prompt = build_system_prompt(datetime.fromisoformat("2026-03-28T14:00"))
    assert "Agora: sábado, 28/03/2026, 14:00" in prompt and status in prompt
    assert unsupported("A equipe volta segunda, 30/03, às 09:00.", [status]) == []

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


def test_late_shipment_is_flagged(tools):
    assert "PREVISÃO VENCIDA" in tools.consultar_pedido(8, "anacarol.ferreira@coldmail.com")


def test_policy_topic_fallback(tools):
    assert "Trocas e devoluções" in tools.consultar_politica("trocas")

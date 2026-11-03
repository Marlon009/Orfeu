from emporio.validator import unsupported

TOOL = """- Takamine GD20 Dreadnought Natural (Violões)
  Preço: R$ 2.199,00 | no PIX: R$ 2.089,05 (5% off) | ou até 12x de R$ 183,25 sem juros
Data da compra: 15/02/2026
Previsão de entrega: 28/02/2026
- Sábado: 09:00 às 13:00"""


def test_values_from_tools_pass():
    answer = ("O GD20 sai por R$ 2.199,00, ou R$2.089,05 no PIX. Comprado em 15/02, "
              "previsto para 28 de fevereiro. Sábado abrimos às 9h e fechamos às 13:00.")
    assert unsupported(answer, [TOOL]) == []


def test_invented_values_are_caught():
    answer = "Custa R$ 1.999,00 e no sábado abrimos das 10:00 às 20h. Chega dia 5 de março."
    assert unsupported(answer, [TOOL]) == ["R$ 1999.00", "data 05/03", "horário 10:00", "horário 20:00"]


def test_customer_budget_is_allowed():
    assert unsupported("Opções até R$1000:", [TOOL, "Quais violões até R$1000?"]) == []


def test_text_without_values():
    assert unsupported("Não vendemos cordas, só instrumentos!", []) == []

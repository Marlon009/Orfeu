"""Barra respostas que citam preço, data ou horário que não veio dos dados consultados.

A resposta pode repetir valores do retorno das ferramentas, do que o próprio cliente
escreveu e do histórico já validado. Qualquer outro R$, data ou horário é tratado
como inventado, e o agente gera de novo ou cai na resposta segura.
"""
import re

MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
          "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}

MONEY = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
DATE_TEXT = re.compile(r"\b(\d{1,2}) de (" + "|".join(MONTHS) + r")\b", re.IGNORECASE)
TIME = re.compile(r"\b(\d{1,2})(?::(\d{2})|h(\d{2})?)\b")


def _money(text: str) -> set[float]:
    return {round(float(i.replace(".", "") + "." + (c or "0")), 2) for i, c in MONEY.findall(text)}


def _dates(text: str) -> set[tuple[int, int]]:
    found = {(int(d), int(m)) for d, m in DATE_NUM.findall(text)}
    found |= {(int(d), MONTHS[m.lower()]) for d, m in DATE_TEXT.findall(text)}
    return found


def _times(text: str) -> set[tuple[int, int]]:
    text = DATE_NUM.sub(" ", text)
    return {(int(h), int(m or mh or 0)) for h, m, mh in TIME.findall(text) if int(h) <= 23}


def unsupported(answer: str, sources: list[str]) -> list[str]:
    """Valores da resposta que não aparecem em nenhuma fonte permitida."""
    allowed = " \n".join(sources)
    problems = [f"R$ {v:.2f}" for v in _money(answer) - _money(allowed)]
    problems += [f"data {d:02d}/{m:02d}" for d, m in _dates(answer) - _dates(allowed)]
    problems += [f"horário {h:02d}:{m:02d}" for h, m in _times(answer) - _times(allowed)]
    return sorted(problems)

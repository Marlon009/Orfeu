"""Regras do manual de políticas, em código: o LLM nunca calcula preço ou prazo."""
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

PIX_DISCOUNT = 0.05
INSTALLMENT_MIN = [(3, 50.0), (6, 80.0), (12, 100.0)]  # (até N parcelas, parcela mínima)
RETURN_DAYS = 7          # arrependimento e troca por preferência, a partir do recebimento
DEFECT_DAYS = 30         # troca por defeito, a partir da compra
LEGAL_WARRANTY_DAYS = 90  # garantia legal, a partir do recebimento

ORDER_STATUS = {
    "pending": "aguardando confirmação do pagamento",
    "confirmed": "pagamento confirmado, pedido em separação",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

PAYMENT_METHODS = {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}


def brl(value: float) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def payment_label(method: str) -> str:
    if method.startswith("credit_"):
        return f"cartão de crédito em {method.removeprefix('credit_')}"
    return PAYMENT_METHODS.get(method, method)


def max_installments(value: float) -> int:
    best = 1
    for n in range(2, 13):
        minimum = next(m for limit, m in INSTALLMENT_MIN if n <= limit)
        if value / n >= minimum:
            best = n
    return best


@dataclass
class Price:
    list_price: float
    final: float
    discount_percent: float | None
    promo_name: str | None
    pix: float | None  # None quando há promoção (descontos não acumulam)
    installments: int

    def describe(self) -> str:
        if self.discount_percent:
            text = (f"de {brl(self.list_price)} por {brl(self.final)} "
                    f"({self.discount_percent:g}% off, promoção {self.promo_name}; "
                    f"desconto do PIX não acumula)")
        else:
            text = f"{brl(self.final)} | no PIX: {brl(self.pix)} (5% off)"
        if self.installments > 1:
            text += f" | ou até {self.installments}x de {brl(self.final / self.installments)} sem juros"
        return text


def price_for(list_price: float, discount_percent: float | None = None, promo_name: str | None = None) -> Price:
    if discount_percent:
        final = round(list_price * (1 - discount_percent / 100), 2)
        pix = None
    else:
        final = list_price
        pix = round(list_price * (1 - PIX_DISCOUNT), 2)
    return Price(list_price, final, discount_percent, promo_name, pix, max_installments(final))


def availability(status: str, stock: int) -> tuple[bool, str]:
    if status == "discontinued":
        return False, "DESCONTINUADO (não faz mais parte do catálogo)"
    if status == "coming_soon":
        return False, "EM BREVE (ainda não disponível para venda)"
    if stock <= 0:
        return False, "ESGOTADO no momento"
    if stock <= 2:
        return True, f"disponível, últimas unidades ({stock} em estoque)"
    return True, f"disponível ({stock} em estoque)"


def _deadline(label: str, end: date, today: date) -> str:
    if today <= end:
        return f"- {label}: DENTRO do prazo (vai até {fmt_date(end)}, faltam {(end - today).days} dias)"
    return f"- {label}: FORA do prazo (encerrou em {fmt_date(end)})"


def return_deadlines(order_date: date, delivered: date, today: date) -> list[tuple[str, str, date, bool]]:
    """(nome curto, rótulo, data final, ainda aberto) de cada prazo de um pedido entregue."""
    windows = [
        ("devolução por arrependimento", "Arrependimento/devolução (7 dias após o recebimento, compras online)", delivered, RETURN_DAYS),
        ("troca por preferência", "Troca por preferência (7 dias)", delivered, RETURN_DAYS),
        ("troca por defeito na loja", "Troca por defeito na loja (30 dias após a compra)", order_date, DEFECT_DAYS),
        ("garantia legal contra defeito", "Garantia legal (90 dias após o recebimento)", delivered, LEGAL_WARRANTY_DAYS),
    ]
    return [(short, label, start + timedelta(days=days), today <= start + timedelta(days=days))
            for short, label, start, days in windows]


def return_windows(order_date: date, delivered: date, today: date) -> str:
    """Prazos de troca/devolução/garantia de um pedido entregue, com a conclusão já pronta."""
    deadlines = return_deadlines(order_date, delivered, today)
    lines = [_deadline(label, end, today) for _, label, end, _ in deadlines]
    still_open = [short for short, _, _, is_open in deadlines if is_open]
    if still_open:
        conclusion = "Ainda vale: " + ", ".join(still_open) + ". O resto NÃO é mais possível."
    else:
        conclusion = ("Nenhum prazo da loja está aberto. Resta só a garantia do fabricante "
                      "(6 meses a 2 anos, ver certificado), que a loja pode intermediar.")
    return "\n".join(lines + [f"CONCLUSÃO: {conclusion}"])


# Horário da loja e do atendimento humano (manual, seção 2). Feriados não estão nos dados.
OPENING_HOURS = {0: (9, 18), 1: (9, 18), 2: (9, 18), 3: (9, 18), 4: (9, 18), 5: (9, 13)}
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def next_opening(now: datetime) -> tuple[str, date, int] | None:
    """None se a loja está aberta; senão (quando, dia, hora) da volta da equipe."""
    hours = OPENING_HOURS.get(now.weekday())
    if hours and hours[0] <= now.hour < hours[1]:
        return None
    for days_ahead in range(0, 8):
        day = now + timedelta(days=days_ahead)
        opening = OPENING_HOURS.get(day.weekday())
        if opening and (days_ahead > 0 or now.hour < opening[0]):
            when = "hoje" if days_ahead == 0 else ("amanhã" if days_ahead == 1 else WEEKDAYS[day.weekday()])
            return when, day.date(), opening[0]
    return None


def store_status(now: datetime) -> str:
    """Se a loja está aberta agora e, se não, quando a equipe volta (manual, seção 7.1)."""
    reopening = next_opening(now)
    if reopening is None:
        return f"Loja ABERTA agora (fecha às {OPENING_HOURS[now.weekday()][1]:02d}:00); a equipe humana está atendendo."
    when, day, hour = reopening
    return (f"Loja FECHADA agora. A equipe humana volta {when} ({fmt_date(day)}) às {hour:02d}:00. "
            "Informe isso se o cliente precisar de uma pessoa da equipe.")


STOPWORDS = {"de", "da", "do", "das", "dos", "o", "a", "os", "as", "um", "uma", "para", "com",
             "e", "em", "ate", "r", "quero", "tem", "voces", "algum", "alguma", "modelo"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def stem(token: str) -> str:
    if token.endswith("oes"):
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    words = "".join(c if c.isalnum() else " " for c in normalize(text)).split()
    return [stem(w) for w in words if w not in STOPWORDS]

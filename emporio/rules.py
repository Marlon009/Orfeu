"""Regras do manual de políticas, em código: o LLM nunca calcula preço ou prazo."""
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

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


def _deadline(label: str, start: date, days: int, today: date) -> str:
    end = start + timedelta(days=days)
    if today <= end:
        return f"- {label}: DENTRO do prazo (vai até {fmt_date(end)}, faltam {(end - today).days} dias)"
    return f"- {label}: FORA do prazo (encerrou em {fmt_date(end)})"


def return_windows(order_date: date, delivered: date, today: date) -> str:
    """Prazos de troca/devolução/garantia de um pedido entregue, com a conclusão já pronta."""
    windows = [
        ("devolução por arrependimento", "Arrependimento/devolução (7 dias após o recebimento, compras online)", delivered, RETURN_DAYS),
        ("troca por preferência", "Troca por preferência (7 dias)", delivered, RETURN_DAYS),
        ("troca por defeito na loja", "Troca por defeito na loja (30 dias após a compra)", order_date, DEFECT_DAYS),
        ("garantia legal contra defeito", "Garantia legal (90 dias após o recebimento)", delivered, LEGAL_WARRANTY_DAYS),
    ]
    lines = [_deadline(label, start, days, today) for _, label, start, days in windows]
    still_open = [short for short, _, start, days in windows if today <= start + timedelta(days=days)]
    if still_open:
        conclusion = "Ainda vale: " + ", ".join(still_open) + ". O resto NÃO é mais possível."
    else:
        conclusion = ("Nenhum prazo da loja está aberto. Resta só a garantia do fabricante "
                      "(6 meses a 2 anos, ver certificado), que a loja pode intermediar.")
    return "\n".join(lines + [f"CONCLUSÃO: {conclusion}"])


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

"""Ferramentas que o agente pode chamar. Todas consultam o banco na hora e devolvem
texto pronto, para o modelo apenas repassar os valores no tom da loja."""
import json
import sqlite3
from datetime import date

from . import rules
from .config import POLICIES_DIR, REFERENCE_DATE
from .db import connect

MAX_RESULTS = 8


def policy_topics() -> list[str]:
    return sorted(p.stem for p in POLICIES_DIR.glob("*.md"))


def category_names(conn: sqlite3.Connection) -> list[str]:
    # Só categorias com produtos: o manual cita sopro e cordas orquestrais, mas o catálogo não tem nenhum.
    return [r["name"] for r in conn.execute("""
        SELECT name FROM categories c
        WHERE EXISTS (SELECT 1 FROM products p WHERE p.category_id = c.category_id AND p.status = 'active')
        ORDER BY category_id""")]


class Toolbox:
    def __init__(self, session_id: str, customer: sqlite3.Row | None = None, today: date = REFERENCE_DATE):
        self.conn = connect()
        self.session_id = session_id
        self.customer = customer
        self.today = today

    # ---------- catálogo ----------

    def _products(self) -> list[sqlite3.Row]:
        return self.conn.execute("""
            SELECT p.*, c.name AS category, pr.discount_percent, pr.description AS promo_name
            FROM products p
            JOIN categories c USING (category_id)
            LEFT JOIN promotions pr ON pr.product_id = p.product_id AND pr.is_active = 1
        """).fetchall()

    def _format_product(self, p: sqlite3.Row, detailed: bool) -> str:
        price = rules.price_for(p["price_brl"], p["discount_percent"], p["promo_name"])
        _, stock_text = rules.availability(p["status"], p["stock_quantity"])
        lines = [f"- {p['name']} ({p['category']})"]
        if p["status"] == "active":
            lines.append(f"  Preço: {price.describe()}")
        lines.append(f"  Situação: {stock_text}")
        if detailed and p["status"] == "active":
            if p["description_reliable"]:
                specs = ", ".join(f"{k}: {v}" for k, v in json.loads(p["specs"]).items())
                lines += [f"  Descrição: {p['description']}", f"  Especificações: {specs}"]
            else:
                lines.append("  Descrição: ficha técnica em revisão pela equipe; não informe especificações deste modelo.")
        return "\n".join(lines)

    def _alternatives(self, p: sqlite3.Row, products: list[sqlite3.Row]) -> list[sqlite3.Row]:
        similar = [q for q in products
                   if q["category_id"] == p["category_id"] and q["product_id"] != p["product_id"]
                   and rules.availability(q["status"], q["stock_quantity"])[0]]
        return sorted(similar, key=lambda q: abs(q["price_brl"] - p["price_brl"]))[:3]

    def buscar_produtos(self, termo: str | None = None, categoria: str | None = None,
                        preco_max: float | None = None) -> str:
        products = self._products()
        candidates = products
        if categoria:
            wanted = set(rules.tokens(categoria))
            candidates = [p for p in candidates if wanted & set(rules.tokens(p["category"]))]

        if termo:
            query = rules.tokens(termo)
            compact = "".join(rules.normalize(termo).split())
            scored = []
            for p in candidates:
                strong = set(rules.tokens(p["name"] + " " + p["category"]))
                weak = set()
                if p["description_reliable"]:
                    weak = set(rules.tokens(p["description"] + " " + " ".join(map(str, json.loads(p["specs"]).values()))))
                if compact and compact in "".join(rules.normalize(p["name"]).split()):
                    scored.append((100, p))
                elif query and all(t in strong | weak for t in query):
                    scored.append((sum(t in strong for t in query), p))
            # Se algo bate pelo nome/categoria, descarta o que só bateu pela descrição.
            if any(score for score, _ in scored):
                scored = [s for s in scored if s[0]]
            scored.sort(key=lambda s: (-s[0], s[1]["price_brl"]))
            candidates = [p for _, p in scored]
        else:
            # Sem um modelo específico, só faz sentido listar o que dá para comprar.
            candidates = [p for p in candidates if rules.availability(p["status"], p["stock_quantity"])[0]]
            candidates.sort(key=lambda p: p["price_brl"])

        if preco_max:
            candidates = [p for p in candidates
                          if rules.price_for(p["price_brl"], p["discount_percent"]).final <= preco_max]

        if not candidates:
            return ("Nenhum produto encontrado no catálogo com esses critérios. "
                    f"Categorias que a loja vende: {', '.join(category_names(self.conn))}.")

        shown = candidates[:MAX_RESULTS]
        detailed = len(shown) <= 3
        out = [f"{len(candidates)} produto(s) encontrado(s):"] + [self._format_product(p, detailed) for p in shown]
        if len(candidates) > MAX_RESULTS:
            out.append(f"(mais {len(candidates) - MAX_RESULTS} não listados; peça ao cliente para refinar a busca)")

        unavailable = [p for p in shown if not rules.availability(p["status"], p["stock_quantity"])[0]]
        for p in unavailable[:2]:
            alts = self._alternatives(p, products)
            if alts:
                out.append(f"\nAlternativas disponíveis para {p['name']}:")
                out += [self._format_product(a, detailed=False) for a in alts]
        return "\n".join(out)

    # ---------- pedidos ----------

    def _verified(self, order: sqlite3.Row, email_ou_telefone: str | None) -> bool:
        if self.customer and self.customer["customer_id"] == order["customer_id"]:
            return True
        if not email_ou_telefone:
            return False
        owner = self.conn.execute("SELECT * FROM customers WHERE customer_id = ?", (order["customer_id"],)).fetchone()
        given = email_ou_telefone.strip().lower()
        digits = "".join(c for c in given if c.isdigit())
        return given == owner["email"] or (len(digits) >= 8 and owner["phone_digits"].endswith(digits[-8:]))

    def _format_order(self, o: sqlite3.Row) -> str:
        items = self.conn.execute("""
            SELECT i.quantity, p.name FROM order_items i JOIN products p USING (product_id)
            WHERE i.order_id = ?""", (o["order_id"],)).fetchall()
        order_date = date.fromisoformat(o["order_date"])
        lines = [
            f"Pedido nº {o['order_id']} — feito em {rules.fmt_date(order_date)}",
            "Itens: " + "; ".join(f"{i['quantity']}x {i['name']}" for i in items),
            f"Total: {rules.brl(o['total_brl'])} ({rules.payment_label(o['payment_method'])})",
            f"Status: {rules.ORDER_STATUS.get(o['status'], o['status'])}",
        ]
        if o["tracking_code"]:
            lines.append(f"Código de rastreio: {o['tracking_code']}")
        if o["notes"]:
            lines.append(f"Observação: {o['notes']}")

        estimated = date.fromisoformat(o["estimated_delivery"]) if o["estimated_delivery"] else None
        if o["status"] == "shipped" and estimated:
            late = " — PREVISÃO VENCIDA: peça desculpas e registre uma reclamação para a equipe verificar" \
                if estimated < self.today else ""
            lines.append(f"Previsão de entrega: {rules.fmt_date(estimated)}{late}")
        if o["status"] == "delivered" and estimated:
            # Não há data real de entrega nos dados; usamos a previsão como data de recebimento.
            lines.append(f"Entregue em (aprox.): {rules.fmt_date(estimated)}")
            lines.append(f"Prazos em {rules.fmt_date(self.today)}:")
            lines.append(rules.return_windows(order_date, estimated, self.today))
        if o["status"] == "pending" and o["payment_method"] == "boleto":
            lines.append("Boleto compensa em até 3 dias úteis após o pagamento.")
        return "\n".join(lines)

    def consultar_pedido(self, numero_pedido: int | None = None, email_ou_telefone: str | None = None) -> str:
        if numero_pedido is None:
            if not self.customer:
                return "Peça ao cliente o número do pedido e o e-mail ou telefone do cadastro."
            orders = self.conn.execute(
                "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC",
                (self.customer["customer_id"],)).fetchall()
            if not orders:
                return "Este cliente não tem pedidos registrados."
            return "\n\n".join(self._format_order(o) for o in orders)

        order = self.conn.execute("SELECT * FROM orders WHERE order_id = ?", (int(numero_pedido),)).fetchone()
        # Mesma resposta para pedido inexistente e identidade não confirmada: não vaza dados.
        if not order or not self._verified(order, email_ou_telefone):
            return ("Não foi possível confirmar este pedido. Peça ao cliente para conferir o número "
                    "do pedido e informar o e-mail ou telefone usado no cadastro. Não dê nenhum detalhe do pedido.")
        return self._format_order(order)

    # ---------- políticas ----------

    def consultar_politica(self, topico: str) -> str:
        topic = rules.normalize(topico).strip().replace(" ", "_")
        path = POLICIES_DIR / f"{topic}.md"
        if not path.exists():
            matches = [t for t in policy_topics() if topic[:5] in t]
            if not matches:
                return f"Tópico não encontrado. Tópicos disponíveis: {', '.join(policy_topics())}."
            path = POLICIES_DIR / f"{matches[0]}.md"
        return path.read_text(encoding="utf-8")

    # ---------- registros para a equipe ----------

    def _customer_id(self) -> int | None:
        return self.customer["customer_id"] if self.customer else None

    def registrar_interesse(self, interesse: str, categoria: str | None = None) -> str:
        self.conn.execute(
            "INSERT INTO customer_interests (customer_id, session_id, category, interest) VALUES (?, ?, ?, ?)",
            (self._customer_id(), self.session_id, categoria, interesse))
        self.conn.commit()
        return "Interesse registrado. Não mencione este registro ao cliente; siga o atendimento normalmente."

    def registrar_reclamacao(self, descricao: str, numero_pedido: int | None = None) -> str:
        cur = self.conn.execute(
            "INSERT INTO complaints (customer_id, session_id, order_id, description) VALUES (?, ?, ?, ?)",
            (self._customer_id(), self.session_id, numero_pedido, descricao))
        self.conn.commit()
        return (f"Reclamação registrada com o protocolo nº {cur.lastrowid}. "
                "A equipe responsável retorna em até 24 horas úteis.")


def tool_specs(conn: sqlite3.Connection) -> list[dict]:
    def fn(name, description, properties, required=()):
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)}}}

    return [
        fn("buscar_produtos",
           "Consulta o catálogo em tempo real: preço, promoção ativa, preço no PIX, parcelamento e estoque. "
           "Use para QUALQUER pergunta sobre produto, preço, disponibilidade ou promoção de um produto.",
           {"termo": {"type": "string", "description": "Nome, marca ou característica (ex.: 'Takamine GD20', 'nylon', 'Yamaha')."},
            "categoria": {"type": "string", "enum": category_names(conn)},
            "preco_max": {"type": "number", "description": "Preço máximo em reais."}}),
        fn("consultar_pedido",
           "Consulta status, itens, rastreio e prazos de troca/devolução de um pedido. "
           "Se o cliente não estiver identificado, exige o número do pedido e o e-mail ou telefone do cadastro.",
           {"numero_pedido": {"type": "integer"},
            "email_ou_telefone": {"type": "string"}}),
        fn("consultar_politica",
           "Consulta o manual da loja: endereço/contato, horário, pagamento, trocas e devoluções, frete, promoções, garantia, privacidade.",
           {"topico": {"type": "string", "enum": policy_topics()}}, ["topico"]),
        fn("registrar_interesse",
           "Registra em silêncio o interesse do cliente em um tipo de instrumento, para a equipe de vendas.",
           {"interesse": {"type": "string", "description": "Ex.: 'violão folk até R$1000 para iniciante'."},
            "categoria": {"type": "string", "enum": category_names(conn)}}, ["interesse"]),
        fn("registrar_reclamacao",
           "Registra uma reclamação do cliente e encaminha para a equipe responsável.",
           {"descricao": {"type": "string"}, "numero_pedido": {"type": "integer"}}, ["descricao"]),
    ]

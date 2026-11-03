"""Relatório para o dono da loja: estoque, inconsistências e o que os clientes estão procurando."""
from datetime import date

from . import rules
from .config import LOW_STOCK_THRESHOLD, REFERENCE_DATE
from .db import connect


def report(today: date = REFERENCE_DATE) -> str:
    conn = connect()
    out = [f"# Alertas da Empório da Música — {rules.fmt_date(today)}"]

    def section(title, rows, fmt):
        out.append(f"\n## {title} ({len(rows)})")
        out.extend(fmt(r) for r in rows)
        if not rows:
            out.append("- nada a reportar")

    section("Estoque baixo (produtos ativos)", conn.execute(
        "SELECT name, stock_quantity FROM products WHERE status = 'active' AND stock_quantity BETWEEN 1 AND ? "
        "ORDER BY stock_quantity", (LOW_STOCK_THRESHOLD,)).fetchall(),
        lambda r: f"- {r['name']}: {r['stock_quantity']} un.")

    section("Ativos sem estoque", conn.execute(
        "SELECT name FROM products WHERE status = 'active' AND stock_quantity = 0").fetchall(),
        lambda r: f"- {r['name']}")

    section("Status x estoque incoerente", conn.execute(
        "SELECT name, status, stock_quantity FROM products "
        "WHERE (status = 'discontinued' AND stock_quantity > 0) "
        "OR (status = 'coming_soon' AND product_id IN (SELECT product_id FROM order_items))").fetchall(),
        lambda r: f"- {r['name']}: status {r['status']} com {r['stock_quantity']} un. em estoque/pedidos")

    section("Descrição não confere com o nome do produto", conn.execute(
        "SELECT name, description FROM products WHERE description_reliable = 0").fetchall(),
        lambda r: f"- {r['name']}: \"{r['description'][:60]}...\"")

    totals = conn.execute("""
        SELECT o.order_id, o.total_brl, SUM(i.quantity * p.price_brl) AS items_total
        FROM orders o JOIN order_items i USING (order_id) JOIN products p USING (product_id)
        GROUP BY o.order_id HAVING ABS(o.total_brl - items_total) > 0.01""").fetchall()
    section("Pedidos com total diferente da soma dos itens", totals,
            lambda r: f"- Pedido {r['order_id']}: registrado {rules.brl(r['total_brl'])}, itens somam {rules.brl(r['items_total'])}")

    late = conn.execute("SELECT order_id, estimated_delivery FROM orders WHERE status = 'shipped' AND estimated_delivery < ?",
                        (today.isoformat(),)).fetchall()
    section("Entregas com previsão vencida", late,
            lambda r: f"- Pedido {r['order_id']}: previsto para {rules.fmt_date(date.fromisoformat(r['estimated_delivery']))}")

    stale = conn.execute("SELECT order_id, order_date FROM orders WHERE status = 'pending' AND julianday(?) - julianday(order_date) > 3",
                         (today.isoformat(),)).fetchall()
    section("Pedidos pendentes há mais de 3 dias", stale,
            lambda r: f"- Pedido {r['order_id']}: feito em {rules.fmt_date(date.fromisoformat(r['order_date']))}")

    section("Reclamações abertas", conn.execute(
        "SELECT id, order_id, description FROM complaints WHERE status = 'aberta'").fetchall(),
        lambda r: f"- Protocolo {r['id']}" + (f" (pedido {r['order_id']})" if r["order_id"] else "") + f": {r['description']}")

    section("Interesses registrados pelo agente, por categoria", conn.execute(
        "SELECT COALESCE(category, 'sem categoria') AS category, COUNT(*) AS n FROM customer_interests "
        "GROUP BY 1 ORDER BY n DESC").fetchall(),
        lambda r: f"- {r['category']}: {r['n']}")
    return "\n".join(out)


if __name__ == "__main__":
    print(report())

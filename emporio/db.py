"""Carga dos CSVs brutos em SQLite, com limpeza e flags de qualidade de dados."""
import csv
import json
import sqlite3

from .config import DB_PATH, RAW_DIR

SCHEMA = """
CREATE TABLE categories (category_id INTEGER PRIMARY KEY, name TEXT, description TEXT);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER, price_brl REAL,
    description TEXT, stock_quantity INTEGER, status TEXT, specs TEXT, created_at TEXT,
    description_reliable INTEGER  -- 0 quando a descrição cita outra marca que não a do nome
);
CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY, product_id INTEGER, discount_percent REAL,
    description TEXT, is_active INTEGER
);
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, phone_digits TEXT, email TEXT, city TEXT);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date TEXT, status TEXT,
    total_brl REAL, payment_method TEXT, tracking_code TEXT, estimated_delivery TEXT, notes TEXT
);
CREATE TABLE order_items (order_id INTEGER, product_id INTEGER, quantity INTEGER);
"""

# Tabelas operacionais geradas pelo agente; criadas a cada conexão para bancos antigos ganharem as novas.
OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS customer_interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, session_id TEXT,
    category TEXT, interest TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, session_id TEXT,
    order_id INTEGER, description TEXT, status TEXT DEFAULT 'aberta',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, recipient TEXT, body TEXT,
    status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CATALOG_TABLES = ["categories", "products", "promotions", "customers", "orders", "order_items"]

BRANDS = [
    "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby", "Crafter", "Martin", "Taylor",
    "Takamine", "Kala", "Ohana", "Kalani", "Fender", "Gibson", "Ibanez", "PRS",
    "Music Man", "Pearl", "Tama", "Korg", "Nord", "Roland",
]


def brands_in(text: str) -> set[str]:
    return {b for b in BRANDS if b.lower() in text.lower()}


def description_matches_name(name: str, description: str) -> bool:
    described = brands_in(description)
    return not described or bool(described & brands_in(name))


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        build()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(OPERATIONAL_SCHEMA)
    return conn


def _read(table: str) -> list[dict]:
    with open(RAW_DIR / f"{table}.csv", encoding="utf-8") as f:
        return [{k: (v.strip() or None) for k, v in row.items()} for row in csv.DictReader(f)]


def build() -> None:
    """Recria as tabelas do catálogo a partir dos CSVs, preservando as tabelas operacionais."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    for table in CATALOG_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA + OPERATIONAL_SCHEMA)

    data = {t: _read(t) for t in CATALOG_TABLES}
    for row in data["products"]:
        json.loads(row["specs"] or "{}")  # falha cedo se o JSON vier quebrado
        row["description_reliable"] = int(description_matches_name(row["name"], row["description"] or ""))
    for row in data["customers"]:
        row["phone_digits"] = "".join(c for c in row["phone"] if c.isdigit())
        row["email"] = row["email"].lower()

    for table, rows in data.items():
        cols = list(rows[0])
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [[r[c] for c in cols] for r in rows],
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    build()
    print(f"Banco criado em {DB_PATH}")

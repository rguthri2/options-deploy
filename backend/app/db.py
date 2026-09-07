"""SQLite persistence for orders, the paper trading account, and E*TRADE
OAuth tokens.

Deliberately plain stdlib `sqlite3` (no ORM) -- this is a single-user app
with light traffic, so a thin data-access layer is simpler to reason about
than adding SQLAlchemy. A short-lived connection is opened per call rather
than shared across requests/threads, which is the safe default for sqlite3
under a multi-threaded ASGI server.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from .config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash_balance REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,              -- "paper" | "etrade"
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,          -- "equity" | "option"
    option_type TEXT,                  -- "call" | "put" | NULL for equity
    strike REAL,
    expiration TEXT,
    side TEXT NOT NULL,                -- "buy" | "sell"
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL,          -- "market" | "limit" | "stop" | "stop_limit" | "trailing_stop"
    limit_price REAL,
    stop_price REAL,                   -- "stop" / "stop_limit" trigger level
    trail_amount REAL,                 -- "trailing_stop": fixed $ trail (mutually exclusive with trail_percent)
    trail_percent REAL,                -- "trailing_stop": % trail (mutually exclusive with trail_amount)
    trail_reference_price REAL,        -- "trailing_stop": best price seen since placement; the trail follows this
    time_in_force TEXT NOT NULL DEFAULT 'day',  -- "day" | "gtc"
    status TEXT NOT NULL,              -- "pending" | "filled" | "canceled" | "rejected"
    filled_price REAL,
    filled_at TEXT,
    broker_order_id TEXT,
    rejection_reason TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etrade_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    oauth_token TEXT,
    oauth_token_secret TEXT,
    account_id_key TEXT,
    updated_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added to `orders` after its original release. `CREATE TABLE IF NOT
# EXISTS` never alters an existing table, so an already-deployed database
# needs these added explicitly -- checked against PRAGMA table_info and
# backfilled with ALTER TABLE, once, on every startup (a no-op once applied).
_ORDER_COLUMNS_ADDED_LATER = {
    "stop_price": "REAL",
    "trail_amount": "REAL",
    "trail_percent": "REAL",
    "trail_reference_price": "REAL",
    "time_in_force": "TEXT NOT NULL DEFAULT 'day'",
}


def _migrate_orders_table(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
    for column, decl in _ORDER_COLUMNS_ADDED_LATER.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} {decl}")


def init_db(starting_cash: float) -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)
        _migrate_orders_table(conn)
        row = conn.execute("SELECT 1 FROM paper_account WHERE id = 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO paper_account (id, cash_balance) VALUES (1, ?)", (starting_cash,))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Paper account -----------------------------------------------------

def get_paper_cash_balance() -> float:
    with connection() as conn:
        row = conn.execute("SELECT cash_balance FROM paper_account WHERE id = 1").fetchone()
        return float(row["cash_balance"]) if row else 0.0


def set_paper_cash_balance(new_balance: float) -> None:
    with connection() as conn:
        conn.execute("UPDATE paper_account SET cash_balance = ? WHERE id = 1", (new_balance,))


# --- Orders --------------------------------------------------------------

def insert_order(**fields) -> int:
    fields.setdefault("created_at", now_iso())
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    with connection() as conn:
        cursor = conn.execute(f"INSERT INTO orders ({columns}) VALUES ({placeholders})", tuple(fields.values()))
        return int(cursor.lastrowid)


def update_order(order_id: int, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with connection() as conn:
        conn.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", (*fields.values(), order_id))


def get_order(order_id: int) -> Optional[sqlite3.Row]:
    with connection() as conn:
        return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def list_orders(broker: Optional[str] = None) -> list[sqlite3.Row]:
    with connection() as conn:
        if broker:
            return conn.execute(
                "SELECT * FROM orders WHERE broker = ? ORDER BY id DESC", (broker,)
            ).fetchall()
        return conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()


def list_pending_orders(broker: str) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE broker = ? AND status = 'pending' ORDER BY id ASC", (broker,)
        ).fetchall()


def list_filled_orders(broker: str) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE broker = ? AND status = 'filled' ORDER BY id ASC", (broker,)
        ).fetchall()


# --- E*TRADE tokens --------------------------------------------------------

def get_etrade_tokens() -> Optional[sqlite3.Row]:
    with connection() as conn:
        return conn.execute("SELECT * FROM etrade_tokens WHERE id = 1").fetchone()


def save_etrade_tokens(oauth_token: str, oauth_token_secret: str, account_id_key: Optional[str] = None) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO etrade_tokens (id, oauth_token, oauth_token_secret, account_id_key, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                oauth_token = excluded.oauth_token,
                oauth_token_secret = excluded.oauth_token_secret,
                account_id_key = COALESCE(excluded.account_id_key, etrade_tokens.account_id_key),
                updated_at = excluded.updated_at
            """,
            (oauth_token, oauth_token_secret, account_id_key, now_iso()),
        )


def clear_etrade_tokens() -> None:
    with connection() as conn:
        conn.execute("DELETE FROM etrade_tokens WHERE id = 1")

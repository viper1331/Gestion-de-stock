"""Gestion basique des connexions SQLite."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import ContextManager

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
USERS_DB_PATH = DATA_DIR / "users.db"
STOCK_DB_PATH = DATA_DIR / "stock.db"

logger = logging.getLogger(__name__)

DATA_DIR.mkdir(parents=True, exist_ok=True)
logger.info("[DB] pid=%s STOCK_DB_PATH=%s", os.getpid(), STOCK_DB_PATH.resolve())

_db_lock = RLock()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def _managed_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection that is always closed on exit."""

    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def get_users_connection() -> ContextManager[sqlite3.Connection]:
    return _managed_connection(USERS_DB_PATH)


def get_stock_connection() -> ContextManager[sqlite3.Connection]:
    return _managed_connection(STOCK_DB_PATH)


def init_databases() -> None:
    with _db_lock:
        with get_users_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_username TEXT NOT NULL,
                    sender_role TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS message_recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    recipient_username TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    read_at TIMESTAMP,
                    archived_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS message_rate_limits (
                    sender_username TEXT PRIMARY KEY,
                    window_start_ts INTEGER NOT NULL,
                    count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at);
                CREATE INDEX IF NOT EXISTS idx_message_recipients_recipient
                ON message_recipients(recipient_username, is_archived);
                CREATE INDEX IF NOT EXISTS idx_message_recipients_message
                ON message_recipients(message_id);
                CREATE TABLE IF NOT EXISTS module_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    module TEXT NOT NULL,
                    can_view INTEGER NOT NULL DEFAULT 0,
                    can_edit INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, module)
                );
                CREATE TABLE IF NOT EXISTS user_homepage_config (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );
                CREATE TABLE IF NOT EXISTS user_layouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, page_id)
                );
                CREATE TABLE IF NOT EXISTS user_page_layouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    page_key TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    hidden_blocks_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, page_key)
                );
                """
            )
            _migrate_user_page_layouts(conn)
        with get_stock_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS category_sizes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL COLLATE NOCASE,
                    UNIQUE(category_id, name)
                );
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sku TEXT UNIQUE NOT NULL,
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    size TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    delta INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    contact_name TEXT,
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    UNIQUE(name)
                );
                CREATE TABLE IF NOT EXISTS supplier_modules (
                    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                    module TEXT NOT NULL,
                    PRIMARY KEY (supplier_id, module)
                );
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT,
                    auto_created INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS purchase_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    quantity_ordered INTEGER NOT NULL,
                    quantity_received INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS collaborators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL COLLATE NOCASE,
                    department TEXT,
                    email TEXT,
                    phone TEXT
                );
                CREATE TABLE IF NOT EXISTS dotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collaborator_id INTEGER NOT NULL REFERENCES collaborators(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL,
                    notes TEXT,
                    perceived_at DATE DEFAULT CURRENT_DATE,
                    is_lost INTEGER NOT NULL DEFAULT 0,
                    is_degraded INTEGER NOT NULL DEFAULT 0,
                    allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pharmacy_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pharmacy_category_sizes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL REFERENCES pharmacy_categories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL COLLATE NOCASE,
                    UNIQUE(category_id, name)
                );
                CREATE TABLE IF NOT EXISTS pharmacy_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    dosage TEXT,
                    packaging TEXT,
                    barcode TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 5,
                    expiration_date DATE,
                    location TEXT,
                    category_id INTEGER REFERENCES pharmacy_categories(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS pharmacy_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                    delta INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pharmacy_purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS pharmacy_purchase_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_order_id INTEGER NOT NULL REFERENCES pharmacy_purchase_orders(id) ON DELETE CASCADE,
                    pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                    quantity_ordered INTEGER NOT NULL,
                    quantity_received INTEGER NOT NULL DEFAULT 0
                );
                """
            )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _migrate_user_page_layouts(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "user_layouts") or not _table_exists(conn, "user_page_layouts"):
        return

    existing = conn.execute(
        "SELECT 1 FROM user_page_layouts LIMIT 1"
    ).fetchone()
    if existing is not None:
        return

    rows = conn.execute(
        "SELECT username, page_id, layout_json, updated_at FROM user_layouts"
    ).fetchall()
    if not rows:
        return

    for row in rows:
        page_key = row["page_id"]
        hidden_blocks: set[str] = set()
        layouts_payload: dict[str, list[dict[str, object]]] = {}
        try:
            payload = json.loads(row["layout_json"])
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            raw_layouts = payload.get("layouts", {})
            if isinstance(raw_layouts, dict):
                for breakpoint, items in raw_layouts.items():
                    if not isinstance(items, list):
                        continue
                    cleaned_items: list[dict[str, object]] = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_id = item.get("i")
                        if item.get("hidden") is True and isinstance(item_id, str):
                            hidden_blocks.add(item_id)
                        cleaned = {key: value for key, value in item.items() if key != "hidden"}
                        cleaned_items.append(cleaned)
                    layouts_payload[breakpoint] = cleaned_items
            if isinstance(payload.get("page_id"), str):
                page_key = payload["page_id"]

        layout_json = json.dumps(
            {
                "version": payload.get("version", 1) if isinstance(payload, dict) else 1,
                "page_key": page_key,
                "layouts": layouts_payload,
            },
            ensure_ascii=False,
        )
        hidden_json = json.dumps(sorted(hidden_blocks), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO user_page_layouts (username, page_key, layout_json, hidden_blocks_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username, page_key) DO UPDATE SET
              layout_json = excluded.layout_json,
              hidden_blocks_json = excluded.hidden_blocks_json,
              updated_at = excluded.updated_at
            """,
            (row["username"], page_key, layout_json, hidden_json, row["updated_at"]),
        )

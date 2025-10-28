"""Gestion basique des connexions SQLite."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
USERS_DB_PATH = DATA_DIR / "users.db"
STOCK_DB_PATH = DATA_DIR / "stock.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

_db_lock = RLock()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_users_connection() -> sqlite3.Connection:
    return _connect(USERS_DB_PATH)


def get_stock_connection() -> sqlite3.Connection:
    return _connect(STOCK_DB_PATH)


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
                CREATE TABLE IF NOT EXISTS module_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    module TEXT NOT NULL,
                    can_view INTEGER NOT NULL DEFAULT 0,
                    can_edit INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, module)
                );
                """
            )
        with get_stock_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sku TEXT UNIQUE NOT NULL,
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    size TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 0
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
                    allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pharmacy_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    dosage TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    expiration_date DATE,
                    location TEXT
                );
                """
            )

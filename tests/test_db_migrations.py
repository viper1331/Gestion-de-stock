from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.core import db, services


def test_init_databases_adds_messages_idempotency_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    users_db = data_dir / "users.db"
    core_db = data_dir / "core.db"
    stock_db = data_dir / "stock.db"

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(db, "CORE_DB_PATH", core_db)
    monkeypatch.setattr(db, "STOCK_DB_PATH", stock_db)
    services._db_initialized = False

    with sqlite3.connect(users_db) as conn:
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_username TEXT NOT NULL,
                sender_role TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    db.init_databases()

    with sqlite3.connect(users_db) as conn:
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        index_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
            ).fetchall()
        }

    assert "idempotency_key" in columns
    assert "idx_messages_idempotency" in index_names

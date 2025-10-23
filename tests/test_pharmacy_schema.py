"""Tests liés au module pharmacy_inventory."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from gestion_stock.pharmacy_inventory import PharmacyInventoryManager


@pytest.fixture()
def legacy_pharmacy_db(tmp_path: Path) -> Path:
    """Crée une base SQLite reproduisant un schéma pharmacie incomplet."""

    db_path = tmp_path / "legacy_stock.db"
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
        cursor.execute("INSERT INTO items (name) VALUES ('Doliprane')")
        cursor.execute(
            """
            CREATE TABLE pharmacy_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                lot_number TEXT NOT NULL,
                expiration_date TEXT,
                quantity INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            "INSERT INTO pharmacy_inventory (item_id, lot_number, quantity) VALUES (1, 'LOT-001', 5)"
        )
        conn.commit()
    finally:
        conn.close()

    return db_path


def _noop_log(*_args, **_kwargs) -> None:  # pragma: no cover - utilisé pour les tests
    return None


def test_ensure_schema_migrates_legacy_pharmacy_table(legacy_pharmacy_db: Path) -> None:
    """Vérifie que les colonnes manquantes sont ajoutées sur un ancien schéma."""

    manager = PharmacyInventoryManager(
        db_path_getter=lambda: str(legacy_pharmacy_db),
        lock=threading.Lock(),
        log_stock_movement=_noop_log,
        parse_user_date=lambda value: value,
    )

    manager.ensure_schema()

    conn = sqlite3.connect(legacy_pharmacy_db)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(pharmacy_inventory)")
        columns = {row[1] for row in cursor.fetchall()}
        assert {
            "storage_condition",
            "prescription_required",
            "note",
            "created_at",
            "updated_at",
        }.issubset(columns)
    finally:
        conn.close()

    summary = manager.summarize_stock()
    assert summary["total_batches"] == 1

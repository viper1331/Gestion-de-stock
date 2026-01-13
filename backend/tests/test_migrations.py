import sqlite3

from backend.core import db, models, services


def test_track_low_stock_migration_adds_column_and_allows_updates(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    stock_path = data_dir / "stock.db"
    users_path = data_dir / "users.db"

    with sqlite3.connect(stock_path) as conn:
        conn.executescript(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE NOT NULL,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                size TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
            );
            """
        )
        cursor = conn.execute(
            """
            INSERT INTO items (name, sku, category_id, size, quantity, low_stock_threshold, supplier_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Legacy Item", "LEGACY-001", None, None, 5, 1, None),
        )
        item_id = cursor.lastrowid

    snapshot_dir = data_dir / "inventory_snapshots"
    snapshot_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "STOCK_DB_PATH", stock_path)
    monkeypatch.setattr(db, "USERS_DB_PATH", users_path)
    monkeypatch.setattr(services, "_MIGRATION_LOCK_PATH", data_dir / "schema_migration.lock")
    monkeypatch.setattr(services, "_INVENTORY_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(services, "_db_initialized", False)

    services.ensure_database_ready()

    with db.get_stock_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
        assert "track_low_stock" in columns

    updated = services.update_item(item_id, models.ItemUpdate(track_low_stock=True))
    assert updated.track_low_stock is True

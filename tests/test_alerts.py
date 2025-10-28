import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Optional

import gestion_stock


class DummyStatus:
    def __init__(self) -> None:
        self.value: Optional[str] = None

    def set(self, value: str) -> None:
        self.value = value


class DummyApp:
    def __init__(self) -> None:
        self.status = DummyStatus()
        self.current_user = "tester"

    def winfo_exists(self) -> bool:
        return True

    def after(self, _delay: int, callback) -> None:  # pragma: no cover - simple relay
        callback()


class StockAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        base = Path(self.tempdir.name)
        self.stock_db_path = base / "stock.db"
        self.clothing_db_path = base / "clothing.db"
        self.pharmacy_db_path = base / "pharmacy.db"

        self.original_stock_db = gestion_stock.DB_PATH
        self.original_clothing_db = gestion_stock.CLOTHING_DB_PATH
        self.original_pharmacy_db = gestion_stock.PHARMACY_DB_PATH

        gestion_stock.DB_PATH = str(self.stock_db_path)
        gestion_stock.CLOTHING_DB_PATH = str(self.clothing_db_path)
        gestion_stock.PHARMACY_DB_PATH = str(self.pharmacy_db_path)

        gestion_stock.init_stock_db(gestion_stock.DB_PATH)
        gestion_stock.ensure_clothing_inventory_schema(
            db_path=gestion_stock.CLOTHING_DB_PATH
        )
        gestion_stock.ensure_pharmacy_inventory_schema(
            db_path=gestion_stock.PHARMACY_DB_PATH
        )
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            conn.execute("DELETE FROM stock_alerts")
            conn.commit()

    def tearDown(self) -> None:
        gestion_stock.DB_PATH = self.original_stock_db
        gestion_stock.CLOTHING_DB_PATH = self.original_clothing_db
        gestion_stock.PHARMACY_DB_PATH = self.original_pharmacy_db
        self.tempdir.cleanup()

    def test_stock_alert_schema_includes_modules(self) -> None:
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(stock_alerts)")
            columns = {row[1] for row in cursor.fetchall()}
        self.assertIn("module", columns)
        self.assertIn("entity_id", columns)
        self.assertIn("related_item_id", columns)

    def test_record_and_detect_alerts_per_module(self) -> None:
        gestion_stock.record_stock_alert(
            42,
            "Test habillement",
            module="clothing",
        )
        self.assertTrue(
            gestion_stock.has_recent_alert(42, within_hours=1, module="clothing")
        )
        self.assertFalse(
            gestion_stock.has_recent_alert(42, within_hours=1, module="inventory")
        )
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT module, entity_id, related_item_id FROM stock_alerts ORDER BY id DESC LIMIT 1"
            )
            module, entity_id, related_item_id = cursor.fetchone()
        self.assertEqual(module, "clothing")
        self.assertEqual(entity_id, 42)
        self.assertIsNone(related_item_id)

    def test_alert_manager_scans_all_modules(self) -> None:
        now = datetime.now().isoformat()
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO items (name, quantity, reorder_point, last_updated) VALUES (?, ?, ?, ?)",
                ("Extincteur", 1, 5, now),
            )
            cursor.execute(
                "INSERT INTO items (name, quantity, reorder_point, is_medicine, last_updated) VALUES (?, ?, ?, ?, ?)",
                ("Antalgique", 2, 6, 1, now),
            )
            conn.commit()
        with sqlite3.connect(gestion_stock.CLOTHING_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO clothing_inventory (name, quantity, reorder_point, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("Veste haute visibilité", 1, 4, now),
            )
            conn.commit()

        app = DummyApp()
        manager = gestion_stock.AlertManager(app, threshold=5, auto_start=False)
        try:
            manager.scan_low_stock()
        finally:
            manager.stop()

        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT module, COUNT(*) FROM stock_alerts GROUP BY module"
            )
            rows = dict(cursor.fetchall())

        self.assertIn("inventory", rows)
        self.assertIn("pharmacy", rows)
        self.assertIn("clothing", rows)
        self.assertIsNotNone(app.status.value)


if __name__ == "__main__":  # pragma: no cover - compat exécution directe
    unittest.main()

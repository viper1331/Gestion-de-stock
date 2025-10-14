import sqlite3
import tempfile
import unittest
from pathlib import Path

import gestion_stock


class AdjustItemQuantityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test_stock.db"
        self.original_db_path = gestion_stock.DB_PATH
        gestion_stock.DB_PATH = str(self.db_path)
        gestion_stock.init_stock_db(gestion_stock.DB_PATH)
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO items (name, quantity, last_updated) VALUES (?, ?, ?)",
                ("Chemise blanche", 10, None),
            )
            self.item_id = cursor.lastrowid
            conn.commit()

    def tearDown(self):
        gestion_stock.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def test_adjust_item_quantity_increments_and_logs_movement(self):
        result = gestion_stock.adjust_item_quantity(
            self.item_id,
            5,
            operator="tester",
            source="test_suite",
            note="ajout",
        )
        self.assertEqual(result, (15, 5, 10))
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM items WHERE id = ?", (self.item_id,))
            self.assertEqual(cursor.fetchone()[0], 15)
            cursor.execute(
                """
                SELECT movement_type, quantity_change, operator, source, note
                FROM stock_movements
                WHERE item_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (self.item_id,),
            )
            movement = cursor.fetchone()
        self.assertEqual(movement, ("IN", 5, "tester", "test_suite", "ajout"))

    def test_adjust_item_quantity_prevents_negative_stock(self):
        result = gestion_stock.adjust_item_quantity(
            self.item_id,
            -20,
            operator="tester",
            source="test_suite",
            note="retrait",
        )
        self.assertEqual(result, (0, -10, 10))
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM items WHERE id = ?", (self.item_id,))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute(
                """
                SELECT movement_type, quantity_change, operator, source, note
                FROM stock_movements
                WHERE item_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (self.item_id,),
            )
            movement = cursor.fetchone()
        self.assertEqual(movement, ("OUT", -10, "tester", "test_suite", "retrait"))

    def test_adjust_item_quantity_noop_returns_current_state(self):
        result = gestion_stock.adjust_item_quantity(
            self.item_id,
            0,
            operator="tester",
            source="test_suite",
            note="aucun",
        )
        self.assertEqual(result, (10, 0, 10))
        with sqlite3.connect(gestion_stock.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT quantity, last_updated FROM items WHERE id = ?", (self.item_id,))
            quantity, last_updated = cursor.fetchone()
            self.assertEqual(quantity, 10)
            self.assertIsNone(last_updated)
            cursor.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE item_id = ?",
                (self.item_id,),
            )
            movement_count = cursor.fetchone()[0]
        self.assertEqual(movement_count, 0)

    def test_adjust_item_quantity_returns_none_for_unknown_item(self):
        result = gestion_stock.adjust_item_quantity(
            999,
            5,
            operator="tester",
            source="test_suite",
            note="inconnu",
        )
        self.assertIsNone(result)


class UserManagementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.user_db_path = Path(self.tempdir.name) / "test_users.db"
        self.original_user_db_path = gestion_stock.USER_DB_PATH
        gestion_stock.USER_DB_PATH = str(self.user_db_path)
        gestion_stock.init_user_db(gestion_stock.USER_DB_PATH)

    def tearDown(self):
        gestion_stock.USER_DB_PATH = self.original_user_db_path
        self.tempdir.cleanup()

    def test_create_user_rejects_invalid_role(self):
        with self.assertRaises(ValueError):
            gestion_stock.create_user("alice", "password", role="manager")


if __name__ == "__main__":
    unittest.main()

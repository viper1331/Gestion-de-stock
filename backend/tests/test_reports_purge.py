from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def setup_module(_: object) -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM pending_clothing_assignments")
        conn.execute("DELETE FROM pharmacy_movements")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()


def _create_user(username: str, password: str, role: str = "user") -> int:
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            (username, username, username.lower(), security.hash_password(password), role),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert row is not None
        return int(row["id"])


def test_reports_purge_requires_admin() -> None:
    _create_user("viewer", "secret123")
    headers = login_headers(client, "viewer", "secret123")
    response = client.post("/admin/reports/purge", json={"module_key": "clothing"}, headers=headers)
    assert response.status_code == 403


def test_reports_purge_clears_module_data_only() -> None:
    _create_user("admin_purger", "secret123", role="admin")
    headers = login_headers(client, "admin_purger", "secret123")
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM pending_clothing_assignments")
        conn.execute("DELETE FROM pharmacy_movements")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        clothing_item_id = conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Gants", "SKU-CL-1", "M", 5, 2, 1),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO movements (item_id, delta, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (clothing_item_id, 3, "Test", "2024-01-01 08:00:00"),
        )
        clothing_order_id = conn.execute(
            """
            INSERT INTO purchase_orders (status, created_at)
            VALUES (?, ?)
            """,
            ("PENDING", "2024-01-01 09:00:00"),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered, quantity_received)
            VALUES (?, ?, ?, ?)
            """,
            (clothing_order_id, clothing_item_id, 4, 0),
        )
        pharmacy_item_id = conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?)
            """,
            ("Paracétamol", 10, 2, 1),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO pharmacy_movements (pharmacy_item_id, delta, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (pharmacy_item_id, 5, "Test", "2024-01-01 08:00:00"),
        )
        pharmacy_order_id = conn.execute(
            """
            INSERT INTO pharmacy_purchase_orders (status, created_at)
            VALUES (?, ?)
            """,
            ("PENDING", "2024-01-01 09:00:00"),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO pharmacy_purchase_order_items (
                purchase_order_id,
                pharmacy_item_id,
                quantity_ordered,
                quantity_received
            )
            VALUES (?, ?, ?, ?)
            """,
            (pharmacy_order_id, pharmacy_item_id, 2, 0),
        )
        conn.commit()

    response = client.post("/admin/reports/purge", json={"module_key": "clothing"}, headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["module_key"] == "clothing"
    assert payload["deleted"]["movements"] == 1
    assert payload["deleted"]["purchase_orders"] == 1
    assert payload["deleted"]["purchase_order_items"] == 1

    with db.get_stock_connection() as conn:
        assert conn.execute("SELECT COUNT(1) AS count FROM movements").fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(1) AS count FROM purchase_orders").fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(1) AS count FROM purchase_order_items").fetchone()[
            "count"
        ] == 0
        assert conn.execute("SELECT COUNT(1) AS count FROM items").fetchone()["count"] == 1
        assert (
            conn.execute("SELECT COUNT(1) AS count FROM pharmacy_movements").fetchone()["count"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(1) AS count FROM pharmacy_purchase_orders"
            ).fetchone()["count"]
            == 1
        )

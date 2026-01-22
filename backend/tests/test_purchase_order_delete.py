import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM purchase_order_audit_log")
        conn.commit()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username LIKE 'po_%'")
        conn.commit()


def _create_user(
    username: str, password: str, *, role: str, email: str | None = None
) -> int:
    services.ensure_database_ready()
    resolved_email = email or f"{username}@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "DELETE FROM users WHERE email_normalized = ?",
            (resolved_email.lower(),),
        )
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            (username, resolved_email, resolved_email.lower(), security.hash_password(password), role),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        assert row is not None
        return int(row["id"])


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _create_purchase_order() -> int:
    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES (?, ?)",
            ("Fournisseur BC", "supplier@example.com"),
        ).lastrowid
        item_id = conn.execute(
            "INSERT INTO items (name, sku, quantity) VALUES (?, ?, ?)",
            ("Test item", "SKU-PO", 5),
        ).lastrowid
        order_id = conn.execute(
            """
            INSERT INTO purchase_orders (supplier_id, status, created_at)
            VALUES (?, 'PENDING', CURRENT_TIMESTAMP)
            """,
            (supplier_id,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered, quantity_received)
            VALUES (?, ?, 2, 0)
            """,
            (order_id, item_id),
        )
        conn.commit()
        return int(order_id)


def test_delete_purchase_order_requires_admin() -> None:
    _reset_tables()
    _create_user("po_delete_user", "password", role="user", email="user@example.com")
    headers = _login_headers("po_delete_user", "password")
    order_id = _create_purchase_order()

    response = client.delete(f"/purchase-orders/{order_id}", headers=headers)

    assert response.status_code == 403


def test_delete_purchase_order_admin_success() -> None:
    _reset_tables()
    _create_user("po_delete_admin", "password", role="admin")
    headers = _login_headers("po_delete_admin", "password")
    order_id = _create_purchase_order()

    response = client.delete(f"/purchase-orders/{order_id}", headers=headers)

    assert response.status_code == 204
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT COUNT(*) AS count FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        item_row = conn.execute(
            "SELECT COUNT(*) AS count FROM purchase_order_items WHERE purchase_order_id = ?",
            (order_id,),
        ).fetchone()
    assert order_row is not None
    assert order_row["count"] == 0
    assert item_row is not None
    assert item_row["count"] == 0
    with db.get_core_connection() as conn:
        audit_row = conn.execute(
            """
            SELECT action, status
            FROM purchase_order_audit_log
            WHERE purchase_order_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()
    assert audit_row is not None
    assert audit_row["action"] == "delete"
    assert audit_row["status"] == "ok"

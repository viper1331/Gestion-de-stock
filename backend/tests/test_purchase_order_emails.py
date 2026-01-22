import sys
from pathlib import Path

from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services
from backend.services import email_sender
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM purchase_order_email_log")
        conn.execute("DELETE FROM purchase_order_audit_log")
        conn.commit()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username LIKE 'po_%'")
        conn.commit()


def _create_user(
    username: str, password: str, *, role: str, email: str | None = None
) -> tuple[int, str]:
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
        return int(row["id"]), resolved_email


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _create_purchase_order(*, supplier_email: str | None) -> int:
    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES (?, ?)",
            ("Fournisseur BC", supplier_email),
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


def _create_pharmacy_purchase_order(*, supplier_email: str | None) -> int:
    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES (?, ?)",
            ("Fournisseur Pharmacie", supplier_email),
        ).lastrowid
        item_id = conn.execute(
            "INSERT INTO pharmacy_items (name, quantity) VALUES (?, ?)",
            ("Test item pharmacy", 5),
        ).lastrowid
        order_id = conn.execute(
            """
            INSERT INTO pharmacy_purchase_orders (supplier_id, status, created_at)
            VALUES (?, 'PENDING', CURRENT_TIMESTAMP)
            """,
            (supplier_id,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO pharmacy_purchase_order_items (
                purchase_order_id,
                pharmacy_item_id,
                quantity_ordered,
                quantity_received
            )
            VALUES (?, ?, 2, 0)
            """,
            (order_id, item_id),
        )
        conn.commit()
        return int(order_id)


def test_send_purchase_order_to_supplier_success() -> None:
    _reset_tables()
    _, admin_email = _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email="supplier@example.com")

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-123"
        response = client.post(
            f"/purchase-orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["sent_to"] == "supplier@example.com"

    send_email.assert_called_once()
    kwargs = send_email.call_args.kwargs
    assert kwargs["reply_to"] == admin_email
    attachments = kwargs["attachments"]
    assert attachments and attachments[0][2] == "application/pdf"

    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT status, supplier_email, user_email, message_id FROM purchase_order_email_log"
        ).fetchone()
    assert row is not None
    assert row["status"] == "sent"
    assert row["supplier_email"] == "supplier@example.com"
    assert row["user_email"] == admin_email
    assert row["message_id"] == "msg-123"

    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT last_sent_at, last_sent_to, last_sent_by FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    assert row is not None
    assert row["last_sent_at"]
    assert row["last_sent_to"] == "supplier@example.com"
    assert row["last_sent_by"] == admin_email


def test_send_purchase_order_to_supplier_failure_logs() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email="supplier@example.com")

    with patch(
        "backend.core.services.email_sender.send_email",
        side_effect=email_sender.EmailSendError("SMTP down"),
    ):
        response = client.post(
            f"/purchase-orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 500
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT status, error_message FROM purchase_order_email_log"
        ).fetchone()
    assert row is not None
    assert row["status"] == "failed"
    assert row["error_message"]

    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT last_sent_at FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    assert row is not None
    assert row["last_sent_at"] is None


def test_send_purchase_order_requires_permission() -> None:
    _reset_tables()
    _create_user("po_user", "password", role="user")
    headers = _login_headers("po_user", "password")
    order_id = _create_purchase_order(supplier_email="supplier@example.com")

    response = client.post(
        f"/purchase-orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 403


def test_send_purchase_order_missing_supplier_email() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email=None)

    response = client.post(
        f"/purchase-orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    with db.get_core_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM purchase_order_email_log").fetchone()
    assert row is not None
    assert row["count"] == 0


def test_purchase_order_resolves_supplier_email_in_detail_and_list() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email="supplier@example.com")

    detail_response = client.get(f"/purchase-orders/{order_id}", headers=headers)
    assert detail_response.status_code == 200, detail_response.text
    detail_payload = detail_response.json()
    assert detail_payload["supplier_email_resolved"] == "supplier@example.com"
    assert detail_payload["supplier_has_email"] is True
    assert detail_payload["supplier_missing_reason"] is None

    list_response = client.get("/purchase-orders/", headers=headers)
    assert list_response.status_code == 200, list_response.text
    listing = list_response.json()
    assert listing
    resolved = next(item for item in listing if item["id"] == order_id)
    assert resolved["supplier_email_resolved"] == "supplier@example.com"
    assert resolved["supplier_has_email"] is True
    assert resolved["supplier_missing_reason"] is None


def test_send_purchase_order_supplier_deleted_returns_conflict() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email="supplier@example.com")
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM suppliers")
        conn.commit()

    response = client.post(
        f"/purchase-orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"] == "Fournisseur introuvable sur le site actif."


def test_send_purchase_order_supplier_email_missing_returns_bad_request() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_purchase_order(supplier_email=None)

    response = client.post(
        f"/purchase-orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    payload = response.json()
    assert (
        payload["detail"]
        == "Email fournisseur manquant. Ajoutez un email au fournisseur pour activer l'envoi."
    )


def test_send_pharmacy_purchase_order_to_supplier_success() -> None:
    _reset_tables()
    _, admin_email = _create_user("po_admin", "password", role="admin")
    headers = _login_headers("po_admin", "password")
    order_id = _create_pharmacy_purchase_order(supplier_email="supplier@example.com")

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-456"
        response = client.post(
            f"/pharmacy/orders/{order_id}/send-to-supplier",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["sent_to"] == "supplier@example.com"

    send_email.assert_called_once()
    kwargs = send_email.call_args.kwargs
    assert kwargs["reply_to"] == admin_email
    attachments = kwargs["attachments"]
    assert attachments and attachments[0][2] == "application/pdf"

    with db.get_core_connection() as conn:
        row = conn.execute(
            """
            SELECT action, status, recipient_email, module_key
            FROM purchase_order_audit_log
            WHERE module_key = 'pharmacy_orders'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    assert row["action"] == "send_to_supplier"
    assert row["status"] == "ok"
    assert row["recipient_email"] == "supplier@example.com"

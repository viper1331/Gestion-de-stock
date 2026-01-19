import sys
from pathlib import Path

import urllib.parse
from unittest.mock import patch

import pyotp
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services, two_factor_crypto
from backend.services import email_sender

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM purchase_order_email_log")
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


def _create_user(username: str, password: str, *, role: str, email: str) -> int:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            (username, email, email.lower(), security.hash_password(password), role),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        assert row is not None
        return int(row["id"])


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    if payload.get("status") == "totp_enroll_required":
        parsed = urllib.parse.urlparse(payload["otpauth_uri"])
        secret = urllib.parse.parse_qs(parsed.query)["secret"][0]
        code = pyotp.TOTP(secret).now()
        confirm = client.post(
            "/auth/totp/enroll/confirm",
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert confirm.status_code == 200, confirm.text
        token = confirm.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    if payload.get("status") == "2fa_required" and payload.get("method") == "totp":
        with db.get_users_connection() as conn:
            row = conn.execute(
                "SELECT two_factor_secret_enc FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        assert row and row["two_factor_secret_enc"], "Missing 2FA secret for user"
        secret = two_factor_crypto.decrypt_secret(str(row["two_factor_secret_enc"]))
        code = pyotp.TOTP(secret).now()
        verify = client.post(
            "/auth/totp/verify",
            json={"challenge_token": payload["challenge_id"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        token = verify.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    token = payload["access_token"]
    return {"Authorization": f"Bearer {token}"}


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


def test_send_purchase_order_to_supplier_success() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin", email="admin@example.com")
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
    assert kwargs["reply_to"] == "admin@example.com"
    attachments = kwargs["attachments"]
    assert attachments and attachments[0][2] == "application/pdf"

    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT status, supplier_email, user_email, message_id FROM purchase_order_email_log"
        ).fetchone()
    assert row is not None
    assert row["status"] == "sent"
    assert row["supplier_email"] == "supplier@example.com"
    assert row["user_email"] == "admin@example.com"
    assert row["message_id"] == "msg-123"

    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT last_sent_at, last_sent_to, last_sent_by FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    assert row is not None
    assert row["last_sent_at"]
    assert row["last_sent_to"] == "supplier@example.com"
    assert row["last_sent_by"] == "admin@example.com"


def test_send_purchase_order_to_supplier_failure_logs() -> None:
    _reset_tables()
    _create_user("po_admin", "password", role="admin", email="admin@example.com")
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
    _create_user("po_user", "password", role="user", email="user@example.com")
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
    _create_user("po_admin", "password", role="admin", email="admin@example.com")
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

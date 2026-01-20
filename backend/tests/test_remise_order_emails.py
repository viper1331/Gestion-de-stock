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
        conn.execute("DELETE FROM purchase_order_audit_log")
        conn.commit()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM remise_purchase_order_items")
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username LIKE 'remise_%'")
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


def _create_remise_purchase_order(*, supplier_email: str | None) -> tuple[int, int | None]:
    with db.get_stock_connection() as conn:
        supplier_id = None
        if supplier_email is not None:
            supplier_id = conn.execute(
                "INSERT INTO suppliers (name, email) VALUES (?, ?)",
                ("St Martin", supplier_email),
            ).lastrowid
            conn.execute(
                "INSERT INTO supplier_modules (supplier_id, module) VALUES (?, ?)",
                (supplier_id, "inventory_remise"),
            )
        item_id = conn.execute(
            "INSERT INTO remise_items (name, sku, quantity) VALUES (?, ?, ?)",
            ("Matériel test", "REM-1", 3),
        ).lastrowid
        order_id = conn.execute(
            """
            INSERT INTO remise_purchase_orders (supplier_id, status, created_at)
            VALUES (?, 'PENDING', CURRENT_TIMESTAMP)
            """,
            (supplier_id,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO remise_purchase_order_items (
                purchase_order_id,
                remise_item_id,
                quantity_ordered,
                quantity_received
            )
            VALUES (?, ?, 2, 0)
            """,
            (order_id, item_id),
        )
        conn.commit()
        return int(order_id), int(supplier_id) if supplier_id is not None else None


def test_send_remise_purchase_order_to_supplier_success() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email="sebastien.cangemi@orange.fr")

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-456"
        response = client.post(
            f"/remise-inventory/orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["sent_to"] == "sebastien.cangemi@orange.fr"

    send_email.assert_called_once()
    kwargs = send_email.call_args.kwargs
    assert kwargs["reply_to"] == "admin@example.com"
    attachments = kwargs["attachments"]
    assert attachments and attachments[0][2] == "application/pdf"

    with db.get_core_connection() as conn:
        row = conn.execute(
            """
            SELECT status, supplier_email, user_email, module_key
            FROM purchase_order_email_log
            """
        ).fetchone()
    assert row is not None
    assert row["status"] == "sent"
    assert row["supplier_email"] == "sebastien.cangemi@orange.fr"
    assert row["user_email"] == "admin@example.com"
    assert row["module_key"] == "remise_orders"

    with db.get_core_connection() as conn:
        row = conn.execute(
            """
            SELECT status, action, module_key
            FROM purchase_order_audit_log
            """
        ).fetchone()
    assert row is not None
    assert row["status"] == "ok"
    assert row["action"] == "send_to_supplier"
    assert row["module_key"] == "remise_orders"


def test_send_remise_purchase_order_supplier_deleted_returns_bad_request() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email="contact@example.com")
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM suppliers")
        conn.commit()

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Fournisseur introuvable"


def test_send_remise_purchase_order_supplier_email_missing_returns_bad_request() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email="")

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Email fournisseur manquant"


def test_send_remise_purchase_order_invalid_supplier_email_returns_bad_request() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email="invalid")

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Email fournisseur invalide"


def test_send_remise_purchase_order_missing_supplier_returns_bad_request() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email=None)

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Bon de commande non associé à un fournisseur"


def test_send_remise_purchase_order_email_send_failure_logs() -> None:
    _reset_tables()
    _create_user("remise_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("remise_admin", "password")
    order_id, _ = _create_remise_purchase_order(supplier_email="contact@example.com")

    with patch(
        "backend.core.services.email_sender.send_email",
        side_effect=email_sender.EmailSendError("SMTP down"),
    ):
        response = client.post(
            f"/remise-inventory/orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 500
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT status, error_message, module_key FROM purchase_order_email_log"
        ).fetchone()
    assert row is not None
    assert row["status"] == "failed"
    assert row["error_message"]
    assert row["module_key"] == "remise_orders"

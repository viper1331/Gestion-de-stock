import sys
from pathlib import Path
import urllib.parse
from unittest.mock import patch

import pyotp
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services, two_factor_crypto

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM purchase_order_email_log")
        conn.execute("DELETE FROM purchase_order_audit_log")
        conn.commit()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM remise_purchase_order_items")
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username LIKE 'email_send_%'")
        conn.commit()


def _create_user(username: str, password: str, *, role: str, email: str) -> None:
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


def _create_supplier(headers: dict[str, str], *, name: str, email: str | None, module: str) -> int:
    payload = {
        "name": name,
        "email": email,
        "contact_name": None,
        "phone": None,
        "address": None,
        "modules": [module],
    }
    response = client.post("/suppliers/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_remise_item() -> int:
    with db.get_stock_connection() as conn:
        item_id = conn.execute(
            "INSERT INTO remise_items (name, sku, quantity) VALUES (?, ?, ?)",
            ("Gants", "REM-EMAIL-1", 2),
        ).lastrowid
        conn.commit()
        return int(item_id)


def _create_pharmacy_item() -> int:
    with db.get_stock_connection() as conn:
        item_id = conn.execute(
            "INSERT INTO pharmacy_items (name, quantity, low_stock_threshold) VALUES (?, ?, ?)",
            ("Test Pharma", 1, 3),
        ).lastrowid
        conn.commit()
        return int(item_id)


def test_send_remise_order_uses_supplier_email() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Remise",
        email="remise@test.fr",
        module="inventory_remise",
    )
    remise_item_id = _create_remise_item()

    response = client.post(
        "/remise-inventory/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"remise_item_id": remise_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-remise"
        response = client.post(
            f"/remise-inventory/orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 200, response.text
    assert send_email.call_args.args[0] == "remise@test.fr"


def test_send_pharmacy_order_uses_supplier_email() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Pharma",
        email="pharma@test.fr",
        module="pharmacy",
    )
    pharmacy_item_id = _create_pharmacy_item()

    response = client.post(
        "/pharmacy/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"pharmacy_item_id": pharmacy_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-pharma"
        response = client.post(
            f"/pharmacy/orders/{order_id}/send-to-supplier",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert send_email.call_args.args[0] == "pharma@test.fr"


def test_send_order_supplier_deleted_returns_error() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Supprimé",
        email="deleted@test.fr",
        module="inventory_remise",
    )
    remise_item_id = _create_remise_item()

    response = client.post(
        "/remise-inventory/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"remise_item_id": remise_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    response = client.delete(f"/suppliers/{supplier_id}", headers=headers)
    assert response.status_code == 204, response.text

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Fournisseur introuvable"


def test_send_order_supplier_missing_email_returns_error() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin", email="admin@example.com")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Sans Email",
        email="",
        module="pharmacy",
    )
    pharmacy_item_id = _create_pharmacy_item()

    response = client.post(
        "/pharmacy/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"pharmacy_item_id": pharmacy_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    response = client.post(
        f"/pharmacy/orders/{order_id}/send-to-supplier",
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email fournisseur manquant"

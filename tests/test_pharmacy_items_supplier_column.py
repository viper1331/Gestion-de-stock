import sys
import urllib.parse
from pathlib import Path

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
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username = 'pharmacy_admin'")
        conn.commit()


def _create_user(username: str, password: str, *, role: str) -> None:
    services.ensure_database_ready()
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


def _create_supplier(headers: dict[str, str], *, name: str, email: str, module: str) -> int:
    response = client.post(
        "/suppliers/",
        json={
            "name": name,
            "email": email,
            "contact_name": None,
            "phone": None,
            "address": None,
            "modules": [module],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_pharmacy_items_include_supplier_name() -> None:
    _reset_tables()
    _create_user("pharmacy_admin", "password", role="admin")
    headers = _login_headers("pharmacy_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Santé",
        email="contact@fournisseur-sante.fr",
        module="pharmacy",
    )

    response = client.post(
        "/pharmacy/",
        json={
            "name": "Produit Test",
            "quantity": 1,
            "low_stock_threshold": 5,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    response = client.get("/pharmacy/", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert items
    item = next(entry for entry in items if entry["name"] == "Produit Test")
    assert item["supplier_id"] == supplier_id
    assert item["supplier_name"] == "Fournisseur Santé"
    assert item["supplier_email"] == "contact@fournisseur-sante.fr"


def test_pharmacy_items_missing_supplier() -> None:
    _reset_tables()
    _create_user("pharmacy_admin", "password", role="admin")
    headers = _login_headers("pharmacy_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Supprimé",
        email="delete@fournisseur.fr",
        module="pharmacy",
    )

    response = client.post(
        "/pharmacy/",
        json={
            "name": "Produit Sans Fournisseur",
            "quantity": 3,
            "low_stock_threshold": 2,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    response = client.delete(f"/suppliers/{supplier_id}", headers=headers)
    assert response.status_code == 204, response.text

    response = client.get("/pharmacy/", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()
    item = next(entry for entry in items if entry["name"] == "Produit Sans Fournisseur")
    assert item["supplier_id"] == supplier_id
    assert item["supplier_name"] is None
    assert item["supplier_email"] is None

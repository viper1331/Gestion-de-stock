import sys
from pathlib import Path

import urllib.parse

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
        conn.execute("DELETE FROM purchase_suggestion_lines")
        conn.execute("DELETE FROM purchase_suggestions")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username IN ('suggest_admin')")  # pragma: no cover
        conn.commit()


def _create_user(username: str, password: str, role: str = "user") -> int:
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
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
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


def test_suggestion_resolves_supplier_email() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES ('Fournisseur Email', 'contact@test.fr')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Blouse', 'CL-07', 1, 5, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = client.get("/purchasing/suggestions", headers=headers)
    assert response.status_code == 200, response.text
    suggestion = response.json()[0]
    assert suggestion["supplier_email"] == "contact@test.fr"
    assert suggestion["supplier_status"] == "ok"


def test_suggestion_missing_supplier_blocks_conversion() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES ('Fournisseur Supprimé', 'supprime@test.fr')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Chaussures', 'CL-08', 0, 4, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    suggestion_id = response.json()[0]["id"]

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        conn.commit()

    response = client.get("/purchasing/suggestions", headers=headers)
    assert response.status_code == 200, response.text
    suggestion = response.json()[0]
    assert suggestion["supplier_status"] == "missing"

    response = client.post(f"/purchasing/suggestions/{suggestion_id}/convert", headers=headers)
    assert response.status_code == 400


def test_suggestion_no_email_blocks_send() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES ('Fournisseur Sans Email', '')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Masque', 'CL-09', 0, 3, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    suggestion = response.json()[0]
    assert suggestion["supplier_status"] == "no_email"

    response = client.post(
        f"/purchasing/suggestions/{suggestion['id']}/convert",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    order_id = response.json()["purchase_order_id"]

    response = client.post(f"/purchasing/orders/{order_id}/send-to-supplier", headers=headers)
    assert response.status_code == 400

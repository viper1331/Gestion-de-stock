import sys
from pathlib import Path

import urllib.parse

import pyotp
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
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
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM remise_purchase_order_items")
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username IN ('suggest_admin', 'suggest_user')")
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


def _grant_module_permission(user_id: int, module: str, *, can_view: bool, can_edit: bool) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO module_permissions (user_id, module, can_view, can_edit)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, module, int(can_view), int(can_edit)),
        )
        conn.commit()


def test_refresh_idempotent_grouping() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_a = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur A')"
        ).lastrowid
        supplier_b = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur B')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Gants', 'CL-01', 2, 5, 1, ?)
            """,
            (supplier_a,),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Casque', 'CL-02', 1, 4, 1, ?)
            """,
            (supplier_b,),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, supplier_id, track_low_stock)
            VALUES ('Batterie', 'RM-01', 0, 3, ?, 1)
            """,
            (supplier_a,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT module_key, supplier_id, site_key FROM purchase_suggestions WHERE status = 'draft'"
        ).fetchall()
        assert len(rows) == 3

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM purchase_suggestions WHERE status = 'draft'"
        ).fetchall()
        lines = conn.execute("SELECT id FROM purchase_suggestion_lines").fetchall()
        assert len(rows) == 3
        assert len(lines) == 3


def test_convert_suggestion_creates_purchase_order() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur Convert')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Veste', 'CL-03', 1, 5, 1, ?)
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
        line_id = conn.execute(
            "SELECT id FROM purchase_suggestion_lines WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()["id"]

    response = client.patch(
        f"/purchasing/suggestions/{suggestion_id}",
        json={"lines": [{"id": line_id, "qty_final": 7}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/purchasing/suggestions/{suggestion_id}/convert",
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        status_row = conn.execute(
            "SELECT status FROM purchase_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        assert status_row["status"] == "converted"
        order_row = conn.execute(
            "SELECT id FROM purchase_orders WHERE supplier_id = ?",
            (supplier_id,),
        ).fetchone()
        assert order_row is not None
        item_row = conn.execute(
            """
            SELECT quantity_ordered
            FROM purchase_order_items
            WHERE purchase_order_id = ?
            """,
            (order_row["id"],),
        ).fetchone()
        assert item_row["quantity_ordered"] == 7


def test_permissions_filter_modules() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    user_id = _create_user("suggest_user", "password", role="user")
    _grant_module_permission(user_id, "pharmacy", can_view=True, can_edit=False)
    admin_headers = _login_headers("suggest_admin", "password")
    user_headers = _login_headers("suggest_user", "password")

    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES ('Chemise', 'CL-04', 1, 4, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold)
            VALUES ('Bandage', 1, 5)
            """
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "pharmacy"]},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    response = client.get("/purchasing/suggestions", headers=user_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data
    assert all(entry["module_key"] == "pharmacy" for entry in data)

    response = client.get("/purchasing/suggestions", params={"module": "clothing"}, headers=user_headers)
    assert response.status_code == 403, response.text

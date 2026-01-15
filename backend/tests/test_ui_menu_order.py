from __future__ import annotations

from pathlib import Path
import urllib.parse

from fastapi.testclient import TestClient
import pyotp

from backend.app import app
from backend.core import db, security, services, two_factor_crypto


def _create_user(username: str, role: str = "user") -> None:
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (
                username,
                email,
                email_normalized,
                password,
                role,
                is_active,
                status,
                site_key
            )
            VALUES (?, ?, ?, ?, ?, 1, 'active', ?)
            """,
            (username, username, username.lower(), security.hash_password("pass"), role, db.DEFAULT_SITE_KEY),
        )
        conn.commit()


def _init_test_dbs(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    snapshot_dir = data_dir / "inventory_snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "STOCK_DB_PATH", data_dir / "stock.db")
    monkeypatch.setattr(db, "USERS_DB_PATH", data_dir / "users.db")
    monkeypatch.setattr(db, "CORE_DB_PATH", data_dir / "core.db")
    monkeypatch.setattr(services, "_MIGRATION_LOCK_PATH", data_dir / "schema_migration.lock")
    monkeypatch.setattr(services, "_INVENTORY_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(services, "_db_initialized", False)
    services.ensure_database_ready()


def _login_token(username: str, password: str) -> str:
    client = TestClient(app)
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
        return confirm.json()["access_token"]
    if payload.get("status") == "totp_required":
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
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        return verify.json()["access_token"]
    raise AssertionError(f"Unexpected login response: {payload}")


def test_save_menu_order_roundtrip_per_user_site(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("admin", role="admin")

    client = TestClient(app)
    token = _login_token("admin", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    payload_jll = {
        "version": 1,
        "items": [
            {"id": "home_group", "parentId": None, "order": 0},
            {"id": "barcode_group", "parentId": None, "order": 1},
            {"id": "home", "parentId": "home_group", "order": 0},
            {"id": "barcode", "parentId": "barcode_group", "order": 0},
        ],
    }
    payload_gsm = {
        "version": 1,
        "items": [
            {"id": "home_group", "parentId": None, "order": 0},
            {"id": "barcode_group", "parentId": None, "order": 1},
            {"id": "barcode", "parentId": "barcode_group", "order": 0},
            {"id": "home", "parentId": "home_group", "order": 1},
        ],
    }

    put_jll = client.put(
        "/ui/menu-order?menu_key=main_menu",
        headers={**headers, "X-Site-Key": "JLL"},
        json=payload_jll,
    )
    assert put_jll.status_code == 200, put_jll.text
    assert put_jll.json()["items"] == payload_jll["items"]

    get_jll = client.get(
        "/ui/menu-order?menu_key=main_menu",
        headers={**headers, "X-Site-Key": "JLL"},
    )
    assert get_jll.status_code == 200, get_jll.text
    assert get_jll.json()["items"] == payload_jll["items"]

    put_gsm = client.put(
        "/ui/menu-order?menu_key=main_menu",
        headers={**headers, "X-Site-Key": "GSM"},
        json=payload_gsm,
    )
    assert put_gsm.status_code == 200, put_gsm.text
    assert put_gsm.json()["items"] == payload_gsm["items"]

    get_gsm = client.get(
        "/ui/menu-order?menu_key=main_menu",
        headers={**headers, "X-Site-Key": "GSM"},
    )
    assert get_gsm.status_code == 200, get_gsm.text
    assert get_gsm.json()["items"] == payload_gsm["items"]

    get_jll_again = client.get(
        "/ui/menu-order?menu_key=main_menu",
        headers={**headers, "X-Site-Key": "JLL"},
    )
    assert get_jll_again.status_code == 200, get_jll_again.text
    assert get_jll_again.json()["items"] == payload_jll["items"]


def test_menu_order_cannot_move_pinned(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("admin", role="admin")

    client = TestClient(app)
    token = _login_token("admin", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/ui/menu-order?menu_key=main_menu",
        headers=headers,
        json={"version": 1, "items": [{"id": "logout", "parentId": None, "order": 0}]},
    )
    assert response.status_code == 400, response.text


def test_menu_order_reject_unknown_id(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("admin", role="admin")

    client = TestClient(app)
    token = _login_token("admin", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/ui/menu-order?menu_key=main_menu",
        headers=headers,
        json={"version": 1, "items": [{"id": "unknown", "parentId": None, "order": 0}]},
    )
    assert response.status_code == 400, response.text


def test_menu_order_reject_item_parent_is_item(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("admin", role="admin")

    client = TestClient(app)
    token = _login_token("admin", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/ui/menu-order?menu_key=main_menu",
        headers=headers,
        json={
            "version": 1,
            "items": [
                {"id": "home", "parentId": "barcode", "order": 0},
                {"id": "barcode", "parentId": "barcode_group", "order": 0},
            ],
        },
    )
    assert response.status_code == 400, response.text

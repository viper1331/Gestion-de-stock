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
        return verify.json()["access_token"]
    raise AssertionError(f"Unexpected login response: {payload}")


def test_table_prefs_roundtrip_per_user_site(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("user-a")
    _create_user("user-b")

    client = TestClient(app)
    token_a = _login_token("user-a", "pass")
    token_b = _login_token("user-b", "pass")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    payload = {
        "prefs": {
            "v": 1,
            "visible": {"sku": True, "name": True},
            "order": ["sku", "name", "qty"],
            "widths": {"sku": 160, "name": 320}
        }
    }

    put_jll = client.put(
        "/ui/table-prefs/pharmacy.items",
        headers={**headers_a, "X-Site-Key": "JLL"},
        json=payload,
    )
    assert put_jll.status_code == 200, put_jll.text
    assert put_jll.json()["prefs"] == payload["prefs"]

    get_jll = client.get(
        "/ui/table-prefs/pharmacy.items",
        headers={**headers_a, "X-Site-Key": "JLL"},
    )
    assert get_jll.status_code == 200, get_jll.text
    assert get_jll.json()["prefs"] == payload["prefs"]

    get_gsm = client.get(
        "/ui/table-prefs/pharmacy.items",
        headers={**headers_a, "X-Site-Key": "GSM"},
    )
    assert get_gsm.status_code == 200, get_gsm.text
    assert get_gsm.json() is None

    get_user_b = client.get(
        "/ui/table-prefs/pharmacy.items",
        headers={**headers_b, "X-Site-Key": "JLL"},
    )
    assert get_user_b.status_code == 200, get_user_b.text
    assert get_user_b.json() is None


def test_table_prefs_whitelist(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("user-a")

    client = TestClient(app)
    token = _login_token("user-a", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/ui/table-prefs/unknown.items",
        headers=headers,
    )
    assert response.status_code == 400, response.text


def test_table_prefs_validation(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("user-a")

    client = TestClient(app)
    token = _login_token("user-a", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/ui/table-prefs/pharmacy.items",
        headers=headers,
        json={
            "prefs": {
                "v": 1,
                "visible": {"sku": True},
                "order": ["sku"],
                "widths": {"sku": "160"}
            }
        },
    )
    assert response.status_code == 400, response.text

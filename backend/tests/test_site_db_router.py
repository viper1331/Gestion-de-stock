from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pyotp
import urllib.parse

from backend.app import app
from backend.core import db, models, security, services, sites, two_factor_crypto


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


def test_site_selection_follows_assignment_and_override(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("worker", role="user")
    _create_user("admin-site", role="admin")

    sites.set_user_site_assignment("worker", "GSM")
    sites.set_user_site_assignment("admin-site", "JLL")
    sites.set_user_site_override("admin-site", "ST_ELOIS")

    worker = services.get_user("worker")
    admin = services.get_user("admin-site")

    assert worker is not None
    assert admin is not None

    resolved_worker = sites.resolve_site_key(worker, header_site_key=None)
    assert resolved_worker == "GSM"

    resolved_admin_override = sites.resolve_site_key(admin, header_site_key=None)
    assert resolved_admin_override == "ST_ELOIS"

    resolved_admin_header = sites.resolve_site_key(admin, header_site_key="CENTRAL_ENTITY")
    assert resolved_admin_header == "CENTRAL_ENTITY"


def test_non_admin_header_is_ignored(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("user-site", role="user")
    sites.set_user_site_assignment("user-site", "JLL")
    user = services.get_user("user-site")
    assert user is not None

    resolved = sites.resolve_site_key(user, header_site_key="GSM")
    assert resolved == "JLL"


def test_default_site_key_jll_when_missing(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    created = services.create_user(
        models.UserCreate(username="site-default", password="pass12345", role="user")
    )
    assert created.site_key == "JLL"
    fetched = services.get_user("site-default")
    assert fetched is not None
    assert fetched.site_key == "JLL"


def test_non_admin_site_forced_ignores_header(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("viewer", role="user")
    sites.set_user_site_assignment("viewer", "GSM")
    user = services.get_user("viewer")
    assert user is not None
    services.upsert_module_permission(
        models.ModulePermissionUpsert(user_id=user.id, module="clothing", can_view=True, can_edit=False)
    )

    with db.get_stock_connection("GSM") as conn:
        conn.execute("DELETE FROM items")
        conn.execute(
            "INSERT INTO items (name, sku, quantity) VALUES (?, ?, ?)",
            ("GSM Item", "GSM-ITEM", 1),
        )
        conn.commit()
    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM items")
        conn.execute(
            "INSERT INTO items (name, sku, quantity) VALUES (?, ?, ?)",
            ("JLL Item", "JLL-ITEM", 1),
        )
        conn.commit()

    client = TestClient(app)
    token = _login_token("viewer", "pass")
    response = client.get("/items/", headers={"Authorization": f"Bearer {token}", "X-Site-Key": "JLL"})
    assert response.status_code == 200
    skus = {item["sku"] for item in response.json()}
    assert "GSM-ITEM" in skus
    assert "JLL-ITEM" not in skus


def test_admin_can_switch_site(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("admin-switch", role="admin")
    sites.set_user_site_assignment("admin-switch", "JLL")

    with db.get_stock_connection("ST_ELOIS") as conn:
        conn.execute("DELETE FROM items")
        conn.execute(
            "INSERT INTO items (name, sku, quantity) VALUES (?, ?, ?)",
            ("St Elois Item", "STE-ITEM", 1),
        )
        conn.commit()
    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM items")
        conn.execute(
            "INSERT INTO items (name, sku, quantity) VALUES (?, ?, ?)",
            ("JLL Item", "JLL-ITEM", 1),
        )
        conn.commit()

    client = TestClient(app)
    token = _login_token("admin-switch", "pass")
    headers = {"Authorization": f"Bearer {token}"}

    update = client.put("/sites/active", json={"site_key": "ST_ELOIS"}, headers=headers)
    assert update.status_code == 200
    list_items = client.get("/items/", headers=headers)
    assert list_items.status_code == 200
    skus = {item["sku"] for item in list_items.json()}
    assert "STE-ITEM" in skus
    assert "JLL-ITEM" not in skus

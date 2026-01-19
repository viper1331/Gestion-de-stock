from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services

client = TestClient(app)


def _session_version(username: str) -> int:
    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT session_version FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return int(row["session_version"]) if row else 1


def _admin_headers() -> dict[str, str]:
    token = security.create_access_token(
        "admin",
        {"role": "admin", "session_version": _session_version("admin")},
    )
    return {"Authorization": f"Bearer {token}"}


def _user_headers(username: str) -> dict[str, str]:
    token = security.create_access_token(
        username,
        {"role": "user", "session_version": _session_version(username)},
    )
    return {"Authorization": f"Bearer {token}"}


def _create_active_user(username: str, password: str, role: str = "user") -> None:
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


def _create_legacy_user(username: str, password: str, role: str = "user") -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, NULL, NULL, ?, ?, 1, 'active')
            """,
            (username, security.hash_password(password), role),
        )
        conn.commit()


def _user_id_for_email(email: str) -> int:
    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email_normalized = ?",
            (email.lower(),),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def test_register_creates_pending_and_blocks_login() -> None:
    services.ensure_database_ready()
    email = "pending.user@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE email_normalized = ?", (email.lower(),))
        conn.commit()

    response = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["message"] == "Demande envoyée, en attente de validation."

    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT status, is_active FROM users WHERE email_normalized = ?",
            (email.lower(),),
        ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["is_active"] == 0

    login = client.post(
        "/auth/login",
        json={"username": email, "password": "Password123!", "remember_me": False},
    )
    assert login.status_code == 403
    assert login.json()["detail"] == "Compte en attente de validation administrateur."


def test_approve_allows_login() -> None:
    services.ensure_database_ready()
    email = "approved.user@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE email_normalized = ?", (email.lower(),))
        conn.commit()

    response = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!"},
    )
    assert response.status_code == 201
    user_id = _user_id_for_email(email)

    approve = client.post(f"/users/{user_id}/approve", headers=_admin_headers())
    assert approve.status_code == 200, approve.text

    login = client.post(
        "/auth/login",
        json={"username": email, "password": "Password123!", "remember_me": False},
    )
    assert login.status_code == 200, login.text


def test_reject_blocks_login() -> None:
    services.ensure_database_ready()
    email = "rejected.user@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE email_normalized = ?", (email.lower(),))
        conn.commit()

    response = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!"},
    )
    assert response.status_code == 201
    user_id = _user_id_for_email(email)

    reject = client.post(f"/users/{user_id}/reject", headers=_admin_headers())
    assert reject.status_code == 200, reject.text

    login = client.post(
        "/auth/login",
        json={"username": email, "password": "Password123!", "remember_me": False},
    )
    assert login.status_code == 403
    assert login.json()["detail"] == "Compte refusé. Contactez un administrateur."


def test_legacy_username_login_allows_access() -> None:
    services.ensure_database_ready()
    _create_legacy_user("legacy-admin", "LegacyPass123", role="admin")

    login = client.post(
        "/auth/login",
        json={"username": "legacy-admin", "password": "LegacyPass123", "remember_me": False},
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    assert payload["status"] in {"totp_required", "totp_enroll_required"}
    assert payload.get("needs_email_upgrade") is True


def test_register_on_legacy_users_db_migrates_columns(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    users_path = data_dir / "users.db"
    stock_path = data_dir / "stock.db"
    snapshot_dir = data_dir / "inventory_snapshots"
    snapshot_dir.mkdir()

    with sqlite3.connect(users_path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            """
            INSERT INTO users (username, password, role, is_active)
            VALUES (?, ?, 'admin', 1)
            """,
            ("legacy-admin", security.hash_password("LegacyPass123")),
        )
        conn.commit()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "USERS_DB_PATH", users_path)
    monkeypatch.setattr(db, "STOCK_DB_PATH", stock_path)
    monkeypatch.setattr(db, "CORE_DB_PATH", data_dir / "core.db")
    monkeypatch.setattr(services, "_MIGRATION_LOCK_PATH", data_dir / "schema_migration.lock")
    monkeypatch.setattr(services, "_INVENTORY_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(services, "_db_initialized", False)

    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"username": "legacy-admin", "password": "LegacyPass123", "remember_me": False},
        )
        assert login.status_code == 200, login.text

        response = test_client.post(
            "/auth/register",
            json={"email": "legacy.register@example.com", "password": "Password123!"},
        )
        assert response.status_code == 201, response.text

    with db.get_users_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert "email_normalized" in columns
        assert "created_at" in columns
        indices = {row["name"] for row in conn.execute("PRAGMA index_list(users)").fetchall()}
        assert "idx_users_email_normalized" in indices


@pytest.mark.parametrize("endpoint", ["approve", "reject"])
def test_non_admin_cannot_moderate(endpoint: str) -> None:
    services.ensure_database_ready()
    email = f"pending.{endpoint}@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE email_normalized = ?", (email.lower(),))
        conn.commit()

    response = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!"},
    )
    assert response.status_code == 201
    user_id = _user_id_for_email(email)

    _create_active_user("regular-user", "Password123!", role="user")
    response = client.post(
        f"/users/{user_id}/{endpoint}",
        headers=_user_headers("regular-user"),
    )
    assert response.status_code == 403

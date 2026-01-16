from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services

client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    token = security.create_access_token("admin", {"role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _user_headers(username: str) -> dict[str, str]:
    token = security.create_access_token(username, {"role": "user"})
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

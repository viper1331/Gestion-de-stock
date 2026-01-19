from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services

client = TestClient(app)


def _create_active_user(email: str, password: str) -> int:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE email_normalized = ?", (email.lower(),))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, 'user', 1, 'active')
            """,
            (email, email, email.lower(), security.hash_password(password)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE email_normalized = ?",
            (email.lower(),),
        ).fetchone()
    assert row is not None
    return int(row["id"])


@pytest.fixture(autouse=True)
def _cleanup_tables() -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM password_reset_tokens")
        conn.execute("DELETE FROM password_reset_rate_limits")
        conn.commit()


def test_request_unknown_email_is_ok_and_no_token() -> None:
    response = client.post("/auth/password-reset/request", json={"email": "missing@example.com"})
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"ok": True, "dev_reset_token": None}
    with db.get_users_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM password_reset_tokens").fetchone()
    assert row is not None
    assert row["count"] == 0


def test_request_creates_token_and_confirm_resets_password_and_session() -> None:
    email = "reset.user@example.com"
    user_id = _create_active_user(email, "OldPassword123")
    response = client.post("/auth/password-reset/request", json={"email": email})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    dev_token = payload["dev_reset_token"]
    assert dev_token

    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT session_version FROM users WHERE email_normalized = ?",
            (email.lower(),),
        ).fetchone()
    assert row is not None
    old_session_version = int(row["session_version"])

    old_access_token = security.create_access_token(
        email,
        {"role": "user", "session_version": old_session_version},
    )

    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": dev_token, "new_password": "NewPassword123"},
    )
    assert confirm.status_code == 200
    assert confirm.json() == {"ok": True}

    with db.get_users_connection() as conn:
        user_row = conn.execute(
            "SELECT password, session_version FROM users WHERE email_normalized = ?",
            (email.lower(),),
        ).fetchone()
        token_row = conn.execute(
            "SELECT used_at FROM password_reset_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    assert user_row is not None
    assert security.verify_password("NewPassword123", user_row["password"])
    assert int(user_row["session_version"]) == old_session_version + 1

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {old_access_token}"})
    assert me_response.status_code == 401
    assert token_row is not None
    assert token_row["used_at"] is not None


def test_confirm_rejects_invalid_tokens() -> None:
    email = "invalid.token@example.com"
    user_id = _create_active_user(email, "OldPassword123")
    now = datetime.now(timezone.utc)
    expired_at = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, created_at, expires_at, used_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (user_id, services._hash_reset_token("expired-token"), now.isoformat(), expired_at),
        )
        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, created_at, expires_at, used_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                services._hash_reset_token("used-token"),
                now.isoformat(),
                (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                now.isoformat(),
            ),
        )
        conn.commit()

    for token in ("expired-token", "used-token", "unknown-token"):
        response = client.post(
            "/auth/password-reset/confirm",
            json={"token": token, "new_password": "NewPassword123"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Token invalide ou expiré"


def test_password_reset_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    email = "rate.limit@example.com"
    _create_active_user(email, "OldPassword123")
    monkeypatch.setenv("RESET_RATE_LIMIT_COUNT", "1")
    monkeypatch.setenv("RESET_RATE_LIMIT_WINDOW_SECONDS", "3600")

    first = client.post("/auth/password-reset/request", json={"email": email})
    assert first.status_code == 200

    second = client.post("/auth/password-reset/request", json={"email": email})
    assert second.status_code == 429

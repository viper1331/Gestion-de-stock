from __future__ import annotations

import urllib.parse
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient

from backend.app import app
import time

from backend.core import db, security, two_factor, services

client = TestClient(app)


def _create_user(username: str, password: str) -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'user', 1)",
            (username, security.hash_password(password)),
        )


def _login(username: str, password: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "username": username,
        "password": password,
        "remember_me": False,
    }
    if payload:
        body.update(payload)
    response = client.post(
        "/auth/login",
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _enroll_2fa(username: str, password: str) -> str:
    login = _login(username, password)
    assert login["status"] == "totp_enroll_required"
    otpauth_uri = login["otpauth_uri"]
    parsed = urllib.parse.urlparse(otpauth_uri)
    secret = urllib.parse.parse_qs(parsed.query)["secret"][0]
    code = pyotp.TOTP(secret).now()
    confirm = client.post(
        "/auth/totp/enroll/confirm",
        json={"challenge_token": login["challenge_token"], "code": code},
    )
    assert confirm.status_code == 200, confirm.text
    return secret


def test_login_without_2fa_returns_enroll_challenge() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    payload = _login(username, "password123")
    assert payload["status"] == "totp_enroll_required"
    assert payload.get("challenge_token")
    assert payload.get("otpauth_uri")


def test_enroll_confirm_enables_2fa() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    _enroll_2fa(username, "password123")
    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT two_factor_enabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert row["two_factor_enabled"] == 1
    status = client.post(
        "/auth/login",
        json={"username": username, "password": "password123", "remember_me": False},
    )
    assert status.status_code == 200
    assert status.json().get("status") == "totp_required"


def test_two_factor_verification_and_rate_limit() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    secret = _enroll_2fa(username, "password123")
    login = _login(username, "password123")
    challenge_id = login["challenge_token"]
    for _ in range(5):
        response = client.post(
            "/auth/totp/verify",
            json={"challenge_token": challenge_id, "code": "000000"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/auth/totp/verify",
        json={"challenge_token": challenge_id, "code": "000000"},
    )
    assert limited.status_code == 429
    two_factor.clear_rate_limit(username, "testclient")

    login = _login(username, "password123")
    challenge_id = login["challenge_token"]
    code = pyotp.TOTP(secret).now()
    valid = client.post(
        "/auth/totp/verify",
        json={"challenge_token": challenge_id, "code": code},
    )
    assert valid.status_code == 200
    assert "access_token" in valid.json()


def test_challenge_expiration_blocks_verification(monkeypatch) -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    secret = _enroll_2fa(username, "password123")
    monkeypatch.setenv("TWO_FACTOR_CHALLENGE_TTL_SECONDS", "1")
    login = _login(username, "password123")
    challenge_id = login["challenge_token"]
    time.sleep(1.2)
    code = pyotp.TOTP(secret).now()
    response = client.post(
        "/auth/totp/verify",
        json={"challenge_token": challenge_id, "code": code},
    )
    assert response.status_code == 401

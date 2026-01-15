from __future__ import annotations

import urllib.parse
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, two_factor

client = TestClient(app)


def _create_user(username: str, password: str) -> None:
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'user', 1)",
            (username, security.hash_password(password)),
        )


def _login(username: str, password: str) -> dict[str, object]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _enable_2fa(username: str, password: str) -> tuple[str, list[str]]:
    login = _login(username, password)
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    start = client.post("/auth/2fa/setup/start", headers=headers)
    assert start.status_code == 200, start.text
    otpauth_uri = start.json()["otpauth_uri"]
    parsed = urllib.parse.urlparse(otpauth_uri)
    secret = urllib.parse.parse_qs(parsed.query)["secret"][0]
    code = pyotp.TOTP(secret).now()
    confirm = client.post("/auth/2fa/setup/confirm", headers=headers, json={"code": code})
    assert confirm.status_code == 200, confirm.text
    return secret, confirm.json()["recovery_codes"]


def test_login_without_2fa_returns_tokens() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    payload = _login(username, "password123")
    assert "access_token" in payload
    assert "refresh_token" in payload
    assert payload.get("requires_2fa") is None


def test_setup_start_confirm_enables_2fa() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    _, recovery_codes = _enable_2fa(username, "password123")
    assert len(recovery_codes) == 10
    status = client.post(
        "/auth/login",
        json={"username": username, "password": "password123", "remember_me": False},
    )
    assert status.status_code == 200
    assert status.json().get("requires_2fa") is True


def test_two_factor_verification_and_rate_limit() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    secret, _ = _enable_2fa(username, "password123")
    login = _login(username, "password123")
    challenge_id = login["challenge_id"]
    for _ in range(5):
        response = client.post(
            "/auth/2fa/verify",
            json={"challenge_id": challenge_id, "code": "000000", "remember_device": False},
        )
        assert response.status_code == 401
    limited = client.post(
        "/auth/2fa/verify",
        json={"challenge_id": challenge_id, "code": "000000", "remember_device": False},
    )
    assert limited.status_code == 429
    two_factor.clear_rate_limit(username, "testclient")

    login = _login(username, "password123")
    challenge_id = login["challenge_id"]
    code = pyotp.TOTP(secret).now()
    valid = client.post(
        "/auth/2fa/verify",
        json={"challenge_id": challenge_id, "code": code, "remember_device": False},
    )
    assert valid.status_code == 200
    assert "access_token" in valid.json()


def test_recovery_codes_are_one_time() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    _, recovery_codes = _enable_2fa(username, "password123")
    login = _login(username, "password123")
    challenge_id = login["challenge_id"]
    response = client.post(
        "/auth/2fa/recovery",
        json={"challenge_id": challenge_id, "recovery_code": recovery_codes[0], "remember_device": False},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    login = _login(username, "password123")
    challenge_id = login["challenge_id"]
    reused = client.post(
        "/auth/2fa/recovery",
        json={"challenge_id": challenge_id, "recovery_code": recovery_codes[0], "remember_device": False},
    )
    assert reused.status_code == 401


def test_trusted_device_bypasses_2fa() -> None:
    username = f"user-{uuid4().hex[:8]}"
    _create_user(username, "password123")
    secret, _ = _enable_2fa(username, "password123")
    login = _login(username, "password123")
    challenge_id = login["challenge_id"]
    code = pyotp.TOTP(secret).now()
    response = client.post(
        "/auth/2fa/verify",
        json={"challenge_id": challenge_id, "code": code, "remember_device": True},
    )
    assert response.status_code == 200
    bypass = _login(username, "password123")
    assert "access_token" in bypass

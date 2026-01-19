from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from backend.app import app
from backend.core import db, security, services
from backend.services import notifications, system_settings

client = TestClient(app)


def _create_user(username: str, password: str, *, otp_email_enabled: bool = True) -> None:
    services.ensure_database_ready()
    email = f"{username}@example.com"
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
                otp_email_enabled
            )
            VALUES (?, ?, ?, ?, 'user', 1, 'active', ?)
            """,
            (
                username,
                email,
                email.lower(),
                security.hash_password(password),
                1 if otp_email_enabled else 0,
            ),
        )
        conn.commit()


def _configure_email_settings(**otp_overrides: int | bool) -> None:
    system_settings.set_setting_json(
        system_settings.SMTP_SETTINGS_KEY,
        {
            "host": None,
            "port": 587,
            "username": None,
            "from_email": "StockOps <no-reply@localhost>",
            "use_tls": True,
            "use_ssl": False,
            "timeout_seconds": 10,
            "dev_sink": True,
        },
        "tests",
    )
    otp_payload: dict[str, int | bool] = {
        "ttl_minutes": 10,
        "code_length": 6,
        "max_attempts": 5,
        "resend_cooldown_seconds": 45,
        "rate_limit_per_hour": 6,
        "allow_insecure_dev": True,
    }
    otp_payload.update(otp_overrides)
    system_settings.set_setting_json(
        system_settings.OTP_EMAIL_SETTINGS_KEY,
        otp_payload,
        "tests",
    )


@pytest.fixture(autouse=True)
def _clean_email_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM otp_email_challenges")
        conn.execute("DELETE FROM otp_email_rate_limits")
        conn.execute("DELETE FROM email_outbox")
        conn.commit()
    yield


def _login(username: str, password: str) -> dict[str, object]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_login_email_otp_flow_success() -> None:
    _configure_email_settings()
    _create_user("email-otp-user", "password123", otp_email_enabled=True)
    payload = _login("email-otp-user", "password123")
    assert payload["status"] == "2fa_required"
    assert payload["method"] == "email_otp"
    assert payload.get("dev_code")
    verify = client.post(
        "/auth/otp-email/verify",
        json={"challenge_id": payload["challenge_id"], "code": payload["dev_code"]},
    )
    assert verify.status_code == 200, verify.text
    assert "access_token" in verify.json()


def test_login_email_otp_expired() -> None:
    _configure_email_settings()
    _create_user("email-otp-expired", "password123", otp_email_enabled=True)
    payload = _login("email-otp-expired", "password123")
    with db.get_core_connection() as conn:
        conn.execute(
            "UPDATE otp_email_challenges SET expires_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), payload["challenge_id"]),
        )
        conn.commit()
    verify = client.post(
        "/auth/otp-email/verify",
        json={"challenge_id": payload["challenge_id"], "code": payload["dev_code"]},
    )
    assert verify.status_code == 401


def test_login_email_otp_attempt_limit() -> None:
    _configure_email_settings(max_attempts=3, allow_insecure_dev=False)
    _create_user("email-otp-limit", "password123", otp_email_enabled=True)
    payload = _login("email-otp-limit", "password123")
    first = client.post(
        "/auth/otp-email/verify",
        json={"challenge_id": payload["challenge_id"], "code": "000000"},
    )
    assert first.status_code == 401
    second = client.post(
        "/auth/otp-email/verify",
        json={"challenge_id": payload["challenge_id"], "code": "000000"},
    )
    assert second.status_code == 401
    third = client.post(
        "/auth/otp-email/verify",
        json={"challenge_id": payload["challenge_id"], "code": "000000"},
    )
    assert third.status_code == 403


def test_resend_cooldown_429() -> None:
    _configure_email_settings(resend_cooldown_seconds=60, allow_insecure_dev=False)
    _create_user("email-otp-resend", "password123", otp_email_enabled=True)
    payload = _login("email-otp-resend", "password123")
    resend = client.post(
        "/auth/otp-email/resend",
        json={"challenge_id": payload["challenge_id"]},
    )
    assert resend.status_code == 429


def test_outbox_enqueue_and_worker_marks_sent() -> None:
    _configure_email_settings(allow_insecure_dev=False)
    notifications.enqueue_email("test@example.com", "Sujet", "Body")
    result = notifications.run_outbox_once()
    assert result.sent in {0, 1}
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT sent_at FROM email_outbox WHERE to_email = ?",
            ("test@example.com",),
        ).fetchone()
    assert row and row["sent_at"]

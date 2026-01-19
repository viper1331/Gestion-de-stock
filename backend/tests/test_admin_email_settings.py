from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import urllib.parse

from fastapi.testclient import TestClient
import pytest
import pyotp

from backend.app import app
from backend.core import db, security, services
from backend.core import two_factor_crypto
from backend.services import system_settings

client = TestClient(app)


def _login_admin_headers() -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    if payload.get("access_token"):
        return {"Authorization": f"Bearer {payload['access_token']}"}
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
                ("admin",),
            ).fetchone()
        assert row and row["two_factor_secret_enc"], "Missing 2FA secret for admin"
        secret = two_factor_crypto.decrypt_secret(str(row["two_factor_secret_enc"]))
        code = pyotp.TOTP(secret).now()
        verify = client.post(
            "/auth/totp/verify",
            json={"challenge_token": payload["challenge_id"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        token = verify.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    raise AssertionError(f"Unexpected login response: {payload}")


def _create_user(username: str, password: str, *, otp_email_enabled: bool = True) -> int:
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
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    assert row is not None
    return int(row["id"])


def _configure_smtp_settings(*, dev_sink: bool) -> None:
    system_settings.set_setting_json(
        system_settings.SMTP_SETTINGS_KEY,
        {
            "host": "smtp.example.com",
            "port": 587,
            "username": "mailer",
            "from_email": "StockOps <no-reply@example.com>",
            "use_tls": True,
            "use_ssl": False,
            "timeout_seconds": 10,
            "dev_sink": dev_sink,
        },
        "tests",
    )


def _configure_otp_settings(ttl_minutes: int, allow_insecure_dev: bool) -> None:
    system_settings.set_setting_json(
        system_settings.OTP_EMAIL_SETTINGS_KEY,
        {
            "ttl_minutes": ttl_minutes,
            "code_length": 6,
            "max_attempts": 5,
            "resend_cooldown_seconds": 45,
            "rate_limit_per_hour": 6,
            "allow_insecure_dev": allow_insecure_dev,
        },
        "tests",
    )


@pytest.fixture(autouse=True)
def _clean_system_settings() -> None:
    services.ensure_database_ready()
    yield


def test_get_default_settings_from_env_seeded_once(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.seeded.local")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "seed-user")
    monkeypatch.setenv("SMTP_PASSWORD", "seed-pass")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "seeded@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "0")
    monkeypatch.setenv("EMAIL_DEV_SINK", "1")
    monkeypatch.setenv("OTP_EMAIL_TTL_MINUTES", "12")

    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM system_settings WHERE key IN (?, ?)", (
            system_settings.SMTP_SETTINGS_KEY,
            system_settings.OTP_EMAIL_SETTINGS_KEY,
        ))
        conn.commit()

    system_settings.seed_default_system_settings()

    with db.get_core_connection() as conn:
        smtp_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (system_settings.SMTP_SETTINGS_KEY,),
        ).fetchone()
        otp_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (system_settings.OTP_EMAIL_SETTINGS_KEY,),
        ).fetchone()

    assert smtp_row is not None
    smtp_payload = json.loads(smtp_row["value"])
    assert smtp_payload["host"] == "smtp.seeded.local"
    assert smtp_payload["port"] == 2525
    assert smtp_payload["username"] == "seed-user"
    assert "password_enc" in smtp_payload

    assert otp_row is not None
    otp_payload = json.loads(otp_row["value"])
    assert otp_payload["ttl_minutes"] == 12

    monkeypatch.setenv("SMTP_HOST", "smtp.updated.local")
    system_settings.seed_default_system_settings()

    with db.get_core_connection() as conn:
        smtp_row_again = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (system_settings.SMTP_SETTINGS_KEY,),
        ).fetchone()
    smtp_payload_again = json.loads(smtp_row_again["value"])
    assert smtp_payload_again["host"] == "smtp.seeded.local"


def test_put_smtp_settings_encrypts_password_and_get_does_not_return_plain() -> None:
    headers = _login_admin_headers()
    payload = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "user",
        "from_email": "StockOps <no-reply@example.com>",
        "use_tls": True,
        "use_ssl": False,
        "timeout_seconds": 12,
        "dev_sink": False,
        "password": "super-secret"
    }
    response = client.put("/admin/email/smtp-settings", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["smtp_password_set"] is True
    assert "password" not in body

    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (system_settings.SMTP_SETTINGS_KEY,),
        ).fetchone()
    assert row is not None
    stored = json.loads(row["value"])
    assert stored.get("password_enc")
    assert stored["password_enc"] != "super-secret"
    decrypted = system_settings.decrypt_smtp_password(stored["password_enc"])
    assert decrypted == "super-secret"


def test_put_otp_settings_validation() -> None:
    headers = _login_admin_headers()
    payload = {
        "ttl_minutes": 2,
        "code_length": 6,
        "max_attempts": 5,
        "resend_cooldown_seconds": 45,
        "rate_limit_per_hour": 6,
        "allow_insecure_dev": False,
    }
    response = client.put("/admin/email/otp-settings", json=payload, headers=headers)
    assert response.status_code == 400


def test_smtp_test_endpoint_uses_sender_mock(monkeypatch) -> None:
    headers = _login_admin_headers()
    _configure_smtp_settings(dev_sink=False)
    called: dict[str, str] = {}

    def _fake_send(to_email: str, subject: str, body_text: str, body_html: str | None = None, *, sensitive: bool = False) -> None:
        called["to_email"] = to_email
        called["subject"] = subject

    monkeypatch.setattr("backend.api.admin.send_email_smtp", _fake_send)
    response = client.post(
        "/admin/email/smtp-test",
        json={"to_email": "dest@example.com"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert called["to_email"] == "dest@example.com"


def test_otp_email_flow_uses_db_settings() -> None:
    _configure_smtp_settings(dev_sink=True)
    _configure_otp_settings(ttl_minutes=3, allow_insecure_dev=True)
    _create_user("otp-ttl-user", "password123", otp_email_enabled=True)

    response = client.post(
        "/auth/login",
        json={"username": "otp-ttl-user", "password": "password123", "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    challenge_id = payload["challenge_id"]

    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT created_at, expires_at FROM otp_email_challenges WHERE id = ?",
            (challenge_id,),
        ).fetchone()
    assert row is not None
    created_at = datetime.fromisoformat(row["created_at"])
    expires_at = datetime.fromisoformat(row["expires_at"])
    delta = expires_at - created_at
    assert timedelta(minutes=3) <= delta <= timedelta(minutes=3, seconds=5)

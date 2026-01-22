from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import time
import urllib.parse
from typing import Any

from fastapi.testclient import TestClient

from backend.core import db, two_factor_crypto

_pyotp_spec = importlib.util.find_spec("pyotp")
if _pyotp_spec:
    import pyotp
else:
    pyotp = None

_DEFAULT_TOTP_PERIOD_SECONDS = 30
_DEFAULT_TOTP_DIGITS = 6


def _totp_code(secret: str, *, for_time: int | None = None) -> str:
    if pyotp:
        return pyotp.TOTP(secret).now()
    timestep = for_time if for_time is not None else int(time.time())
    counter = int(timestep / _DEFAULT_TOTP_PERIOD_SECONDS)
    key = base64.b32decode(secret.upper(), casefold=True)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(binary % (10**_DEFAULT_TOTP_DIGITS)).zfill(_DEFAULT_TOTP_DIGITS)


def _extract_totp_secret(payload: dict[str, Any]) -> str:
    if payload.get("secret_plain_if_allowed"):
        return str(payload["secret_plain_if_allowed"])
    otpauth_uri = payload.get("otpauth_uri")
    if not otpauth_uri:
        raise AssertionError("Missing otpauth_uri for TOTP enrollment")
    parsed = urllib.parse.urlparse(otpauth_uri)
    secret = urllib.parse.parse_qs(parsed.query).get("secret")
    if not secret:
        raise AssertionError("Missing TOTP secret in otpauth_uri")
    return secret[0]


def _get_user_totp_secret(username: str) -> str:
    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT two_factor_secret_enc FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not row["two_factor_secret_enc"]:
        raise AssertionError("Missing 2FA secret for user")
    return two_factor_crypto.decrypt_secret(str(row["two_factor_secret_enc"]))


def login_token(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("access_token")
    if token:
        return token
    status = payload.get("status")
    if status == "totp_enroll_required":
        secret = _extract_totp_secret(payload)
        code = _totp_code(secret)
        confirm = client.post(
            "/auth/totp/enroll/confirm",
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert confirm.status_code == 200, confirm.text
        return confirm.json()["access_token"]
    if status == "2fa_required":
        method = payload.get("method")
        if method == "totp":
            secret = _get_user_totp_secret(username)
            code = _totp_code(secret)
            verify = client.post(
                "/auth/totp/verify",
                json={"challenge_token": payload["challenge_id"], "code": code},
            )
            assert verify.status_code == 200, verify.text
            return verify.json()["access_token"]
        if method == "email_otp":
            dev_code = payload.get("dev_code")
            assert dev_code, "Missing email OTP dev code"
            verify = client.post(
                "/auth/otp-email/verify",
                json={"challenge_id": payload["challenge_id"], "code": dev_code},
            )
            assert verify.status_code == 200, verify.text
            return verify.json()["access_token"]
    raise AssertionError(f"Unexpected login response: {payload}")


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    token = login_token(client, username, password)
    return {"Authorization": f"Bearer {token}"}

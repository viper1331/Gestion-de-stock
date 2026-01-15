"""Fonctions utilitaires pour l'authentification 2FA (TOTP, recovery, trusted devices)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import pyotp
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from backend.core import db, security

DEFAULT_ISSUER = "Gestion Stock Pro"


class ChallengeError(Exception):
    """Challenge invalide ou expiré."""


class RateLimitError(Exception):
    """Trop de tentatives 2FA."""


@dataclass(frozen=True)
class TrustedDevice:
    username: str
    device_id: str
    token: str
    token_hash: str
    expires_at: datetime


def _get_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(security.SECRET_KEY, salt=salt)


def create_challenge(username: str) -> str:
    payload = {"username": username, "nonce": secrets.token_urlsafe(16)}
    serializer = _get_serializer("two-factor-challenge")
    return serializer.dumps(payload)


def load_challenge(token: str) -> dict[str, Any]:
    serializer = _get_serializer("two-factor-challenge")
    max_age = _get_int_env("TWO_FACTOR_CHALLENGE_TTL_SECONDS", 300)
    try:
        payload = serializer.loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise ChallengeError("Challenge expiré") from exc
    except BadSignature as exc:
        raise ChallengeError("Challenge invalide") from exc
    return payload


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_otpauth_uri(username: str, secret: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=DEFAULT_ISSUER)


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return secret
    return f"{secret[:4]}...{secret[-4:]}"


def verify_totp(secret: str, code: str) -> bool:
    sanitized = code.replace(" ", "")
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(sanitized, valid_window=1))


def generate_recovery_codes(count: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes: list[str] = []
    for _ in range(count):
        chunk = "".join(secrets.choice(alphabet) for _ in range(8))
        codes.append(f"{chunk[:4]}-{chunk[4:]}")
    return codes


def _hash_recovery_code(code: str, salt: str) -> str:
    payload = f"{salt}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_recovery_codes(codes: list[str]) -> list[dict[str, str]]:
    hashed: list[dict[str, str]] = []
    for code in codes:
        salt = secrets.token_hex(16)
        hashed.append({"salt": salt, "hash": _hash_recovery_code(code, salt)})
    return hashed


def verify_recovery_code(stored: list[dict[str, str]], candidate: str) -> tuple[bool, list[dict[str, str]]]:
    normalized = candidate.strip().upper()
    remaining = []
    matched = False
    for entry in stored:
        expected = entry.get("hash", "")
        salt = entry.get("salt", "")
        current = _hash_recovery_code(normalized, salt)
        if not matched and hmac.compare_digest(current, expected):
            matched = True
            continue
        remaining.append(entry)
    return matched, remaining


def serialize_recovery_hashes(hashes: list[dict[str, str]]) -> str:
    return json.dumps(hashes)


def parse_recovery_hashes(raw: Optional[str]) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def create_trusted_device(username: str) -> TrustedDevice:
    device_id = str(uuid4())
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    days = _get_int_env("TWO_FACTOR_TRUSTED_DEVICE_DAYS", 30)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    return TrustedDevice(
        username=username,
        device_id=device_id,
        token=token,
        token_hash=token_hash,
        expires_at=expires_at,
    )


def store_trusted_device(device: TrustedDevice) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_trusted_devices (username, device_id, token_hash, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, device_id) DO UPDATE SET
              token_hash = excluded.token_hash,
              created_at = excluded.created_at,
              expires_at = excluded.expires_at,
              last_seen_at = excluded.last_seen_at
            """,
            (
                device.username,
                device.device_id,
                device.token_hash,
                now,
                device.expires_at.isoformat(),
                now,
            ),
        )


def sign_trusted_device(device: TrustedDevice) -> str:
    serializer = _get_serializer("two-factor-device")
    payload = {"username": device.username, "device_id": device.device_id, "token": device.token}
    return serializer.dumps(payload)


def validate_trusted_device_cookie(cookie_value: str) -> Optional[str]:
    serializer = _get_serializer("two-factor-device")
    max_age = _get_int_env("TWO_FACTOR_TRUSTED_DEVICE_DAYS", 30) * 86400
    try:
        payload = serializer.loads(cookie_value, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    username = payload.get("username")
    device_id = payload.get("device_id")
    token = payload.get("token")
    if not (username and device_id and token):
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT token_hash, expires_at
            FROM user_trusted_devices
            WHERE username = ? AND device_id = ?
            """,
            (username, device_id),
        ).fetchone()
        if not row:
            return None
        if row["token_hash"] != token_hash:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at < datetime.now(timezone.utc):
            return None
        conn.execute(
            """
            UPDATE user_trusted_devices
            SET last_seen_at = ?
            WHERE username = ? AND device_id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), username, device_id),
        )
    return username


def clear_trusted_devices(username: str) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM user_trusted_devices WHERE username = ?",
            (username,),
        )


def check_rate_limit(username: str, ip_address: str) -> None:
    attempts = _get_int_env("TWO_FACTOR_RATE_LIMIT_ATTEMPTS", 5)
    window = _get_int_env("TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS", 300)
    now = int(time.time())
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT window_start_ts, count
            FROM two_factor_rate_limits
            WHERE username = ? AND ip_address = ?
            """,
            (username, ip_address),
        ).fetchone()
        if not row:
            return
        window_start = int(row["window_start_ts"])
        count = int(row["count"])
        if now - window_start > window:
            conn.execute(
                "DELETE FROM two_factor_rate_limits WHERE username = ? AND ip_address = ?",
                (username, ip_address),
            )
            return
        if count >= attempts:
            raise RateLimitError("Too many attempts")


def register_rate_limit_failure(username: str, ip_address: str) -> None:
    window = _get_int_env("TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS", 300)
    now = int(time.time())
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT window_start_ts, count
            FROM two_factor_rate_limits
            WHERE username = ? AND ip_address = ?
            """,
            (username, ip_address),
        ).fetchone()
        if not row or now - int(row["window_start_ts"]) > window:
            conn.execute(
                """
                INSERT OR REPLACE INTO two_factor_rate_limits (username, ip_address, window_start_ts, count)
                VALUES (?, ?, ?, 1)
                """,
                (username, ip_address, now),
            )
            return
        conn.execute(
            """
            UPDATE two_factor_rate_limits
            SET count = count + 1
            WHERE username = ? AND ip_address = ?
            """,
            (username, ip_address),
        )


def clear_rate_limit(username: str, ip_address: str) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM two_factor_rate_limits WHERE username = ? AND ip_address = ?",
            (username, ip_address),
        )

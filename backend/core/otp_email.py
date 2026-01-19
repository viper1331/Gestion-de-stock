"""Email OTP challenge services."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from backend.core import db, security, services
from backend.services import notifications
from backend.services.system_settings import get_email_otp_config


class EmailOtpChallengeError(RuntimeError):
    pass


class EmailOtpRateLimitError(RuntimeError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Trop de demandes OTP")


class EmailOtpCooldownError(RuntimeError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Cooldown en cours")


class EmailOtpAttemptsExceeded(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _get_pepper() -> str:
    return os.getenv("OTP_EMAIL_PEPPER") or security.SECRET_KEY


def _hash_code(code: str, challenge_id: str) -> str:
    payload = f"{code}{_get_pepper()}{challenge_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _generate_code(length: int) -> str:
    max_value = 10 ** length
    code_int = secrets.randbelow(max_value)
    return f"{code_int:0{length}d}"


def _rate_limit_key(prefix: str, value: str | None) -> str | None:
    if not value:
        return None
    return f"{prefix}:{value.strip().lower()}"


def _build_device_hint(user_agent: str | None, request_ip: str | None) -> str | None:
    hint_parts = []
    if user_agent:
        hint_parts.append(user_agent)
    if request_ip:
        hint_parts.append(f"IP {request_ip}")
    if not hint_parts:
        return None
    return " - ".join(hint_parts)


def _enforce_rate_limit(conn, key: str, limit: int) -> None:
    now = _utc_now()
    window_start = now - timedelta(hours=1)
    row = conn.execute(
        "SELECT window_start, count FROM otp_email_rate_limits WHERE key = ?",
        (key,),
    ).fetchone()
    if row:
        current_start = _parse_iso(row["window_start"])
        count = int(row["count"])
        if current_start >= window_start:
            if count >= limit:
                retry_after = int((current_start + timedelta(hours=1) - now).total_seconds())
                raise EmailOtpRateLimitError(retry_after_seconds=max(1, retry_after))
            conn.execute(
                "UPDATE otp_email_rate_limits SET count = ? WHERE key = ?",
                (count + 1, key),
            )
            return
        conn.execute(
            "UPDATE otp_email_rate_limits SET window_start = ?, count = 1 WHERE key = ?",
            (now.isoformat(), key),
        )
        return
    conn.execute(
        "INSERT INTO otp_email_rate_limits (key, window_start, count) VALUES (?, ?, 1)",
        (key, now.isoformat()),
    )


def _ensure_delivery_available() -> None:
    if notifications.is_email_delivery_available():
        return
    raise EmailOtpChallengeError("OTP e-mail indisponible, SMTP non configuré.")


def create_email_otp_challenge(
    user_id: int,
    email: str,
    request_ip: str | None,
    user_agent: str | None,
) -> tuple[str, str | None, int]:
    services.ensure_database_ready()
    _ensure_delivery_available()
    settings = get_email_otp_config()
    normalized_email = email.strip().lower()
    now = _utc_now()
    challenge_id = secrets.token_urlsafe(32)
    code = _generate_code(settings.code_length)
    code_hash = _hash_code(code, challenge_id)
    expires_at = (now + timedelta(minutes=settings.ttl_minutes)).isoformat()
    email_key = _rate_limit_key("email", normalized_email)
    ip_key = _rate_limit_key("ip", request_ip)
    with db.get_core_connection() as conn:
        if email_key:
            _enforce_rate_limit(conn, email_key, settings.rate_limit_per_hour)
        if ip_key:
            _enforce_rate_limit(conn, ip_key, settings.rate_limit_per_hour)
        subject, body_text, body_html = notifications.build_login_otp_email(
            code,
            settings.ttl_minutes,
            _build_device_hint(user_agent, request_ip),
        )
        conn.execute(
            """
            INSERT INTO otp_email_challenges (
                id,
                user_id,
                code_hash,
                created_at,
                expires_at,
                used_at,
                attempt_count,
                last_sent_at,
                request_ip,
                user_agent
            )
            VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?, ?)
            """,
            (
                challenge_id,
                user_id,
                code_hash,
                now.isoformat(),
                expires_at,
                now.isoformat(),
                request_ip,
                user_agent,
            ),
        )
        conn.execute(
            """
            INSERT INTO email_outbox (
                to_email,
                subject,
                body_text,
                body_html,
                created_at,
                sent_at,
                send_attempts,
                last_error,
                priority
            )
            VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, 1)
            """,
            (normalized_email, subject, body_text, body_html, now.isoformat()),
        )
        conn.commit()
    dev_code = code if settings.allow_insecure_dev else None
    return challenge_id, dev_code, settings.resend_cooldown_seconds


def resend_email_otp_challenge(
    challenge_id: str,
    request_ip: str | None,
    user_agent: str | None,
) -> tuple[str | None, int]:
    services.ensure_database_ready()
    _ensure_delivery_available()
    settings = get_email_otp_config()
    now = _utc_now()
    with db.get_core_connection() as core_conn:
        row = core_conn.execute(
            """
            SELECT user_id, expires_at, used_at, attempt_count, last_sent_at
            FROM otp_email_challenges
            WHERE id = ?
            """,
            (challenge_id,),
        ).fetchone()
        if not row:
            raise EmailOtpChallengeError("Challenge invalide")
        if row["used_at"]:
            raise EmailOtpChallengeError("Challenge invalide")
        if _parse_iso(row["expires_at"]) <= now:
            raise EmailOtpChallengeError("Challenge expiré")
        last_sent = _parse_iso(row["last_sent_at"])
        cooldown_remaining = settings.resend_cooldown_seconds - int((now - last_sent).total_seconds())
        if cooldown_remaining > 0:
            raise EmailOtpCooldownError(retry_after_seconds=cooldown_remaining)
        user_row = None
        with db.get_users_connection() as users_conn:
            user_row = users_conn.execute(
                "SELECT email, email_normalized FROM users WHERE id = ?",
                (row["user_id"],),
            ).fetchone()
        if not user_row or not user_row["email"]:
            raise EmailOtpChallengeError("Email manquant")
        email = user_row["email_normalized"] or user_row["email"]
        email_key = _rate_limit_key("email", email)
        ip_key = _rate_limit_key("ip", request_ip)
        if email_key:
            _enforce_rate_limit(core_conn, email_key, settings.rate_limit_per_hour)
        if ip_key:
            _enforce_rate_limit(core_conn, ip_key, settings.rate_limit_per_hour)
        code = _generate_code(settings.code_length)
        subject, body_text, body_html = notifications.build_login_otp_email(
            code,
            settings.ttl_minutes,
            _build_device_hint(user_agent, request_ip),
        )
        code_hash = _hash_code(code, challenge_id)
        expires_at = (now + timedelta(minutes=settings.ttl_minutes)).isoformat()
        core_conn.execute(
            """
            UPDATE otp_email_challenges
            SET code_hash = ?, last_sent_at = ?, expires_at = ?, request_ip = ?, user_agent = ?
            WHERE id = ?
            """,
            (
                code_hash,
                now.isoformat(),
                expires_at,
                request_ip,
                user_agent,
                challenge_id,
            ),
        )
        core_conn.execute(
            """
            INSERT INTO email_outbox (
                to_email,
                subject,
                body_text,
                body_html,
                created_at,
                sent_at,
                send_attempts,
                last_error,
                priority
            )
            VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, 1)
            """,
            (email, subject, body_text, body_html, now.isoformat()),
        )
        core_conn.commit()
    dev_code = code if settings.allow_insecure_dev else None
    return dev_code, settings.resend_cooldown_seconds


def verify_email_otp(challenge_id: str, code: str) -> int:
    services.ensure_database_ready()
    settings = get_email_otp_config()
    now = _utc_now()
    with db.get_core_connection() as conn:
        row = conn.execute(
            """
            SELECT user_id, code_hash, expires_at, used_at, attempt_count
            FROM otp_email_challenges
            WHERE id = ?
            """,
            (challenge_id,),
        ).fetchone()
        if not row:
            raise EmailOtpChallengeError("Challenge invalide")
        if row["used_at"]:
            raise EmailOtpChallengeError("Challenge invalide")
        if _parse_iso(row["expires_at"]) <= now:
            raise EmailOtpChallengeError("Challenge expiré")
        attempts = int(row["attempt_count"])
        if attempts >= settings.max_attempts:
            conn.execute(
                "UPDATE otp_email_challenges SET used_at = ? WHERE id = ?",
                (now.isoformat(), challenge_id),
            )
            conn.commit()
            raise EmailOtpAttemptsExceeded("Limite atteinte")
        expected_hash = row["code_hash"]
        candidate_hash = _hash_code(code.strip(), challenge_id)
        if not hmac.compare_digest(candidate_hash, expected_hash):
            attempts += 1
            used_at = now.isoformat() if attempts >= settings.max_attempts else None
            conn.execute(
                """
                UPDATE otp_email_challenges
                SET attempt_count = ?, used_at = COALESCE(used_at, ?)
                WHERE id = ?
                """,
                (attempts, used_at, challenge_id),
            )
            conn.commit()
            if attempts >= settings.max_attempts:
                raise EmailOtpAttemptsExceeded("Limite atteinte")
            raise EmailOtpChallengeError("Code invalide")
        conn.execute(
            "UPDATE otp_email_challenges SET used_at = ? WHERE id = ?",
            (now.isoformat(), challenge_id),
        )
        return int(row["user_id"])

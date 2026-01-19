"""System settings storage and retrieval."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

from backend.core import db
from backend.core.two_factor_crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

SMTP_SETTINGS_KEY = "email.smtp"
OTP_EMAIL_SETTINGS_KEY = "email.otp"

_DEFAULT_FROM_EMAIL = "StockOps <no-reply@localhost>"


@dataclass(frozen=True)
class SmtpConfig:
    host: str | None
    port: int
    username: str | None
    password: str | None
    from_email: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int
    dev_sink: bool


@dataclass(frozen=True)
class OtpEmailConfig:
    ttl_minutes: int
    code_length: int
    max_attempts: int
    resend_cooldown_seconds: int
    rate_limit_per_hour: int
    allow_insecure_dev: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip() in {"1", "true", "True", "yes", "YES"}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _smtp_env_defaults() -> dict[str, Any]:
    return {
        "host": os.getenv("SMTP_HOST"),
        "port": _get_int_env("SMTP_PORT", 587),
        "username": os.getenv("SMTP_USERNAME"),
        "password": os.getenv("SMTP_PASSWORD"),
        "from_email": os.getenv("SMTP_FROM_EMAIL", _DEFAULT_FROM_EMAIL),
        "use_tls": _get_bool_env("SMTP_USE_TLS", True),
        "use_ssl": _get_bool_env("SMTP_USE_SSL", False),
        "timeout_seconds": _get_int_env("SMTP_TIMEOUT_SECONDS", 10),
        "dev_sink": _get_bool_env("EMAIL_DEV_SINK", False),
    }


def _otp_env_defaults() -> dict[str, Any]:
    return {
        "ttl_minutes": max(1, _get_int_env("OTP_EMAIL_TTL_MINUTES", 10)),
        "code_length": max(4, _get_int_env("OTP_EMAIL_CODE_LENGTH", 6)),
        "max_attempts": max(1, _get_int_env("OTP_EMAIL_MAX_ATTEMPTS", 5)),
        "resend_cooldown_seconds": max(5, _get_int_env("OTP_EMAIL_RESEND_COOLDOWN_SECONDS", 45)),
        "rate_limit_per_hour": max(1, _get_int_env("OTP_EMAIL_RATE_LIMIT_PER_HOUR", 6)),
        "allow_insecure_dev": os.getenv("ALLOW_INSECURE_EMAIL_DEV") == "1",
    }


def get_setting_json(key: str) -> dict[str, Any] | None:
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    try:
        parsed = json.loads(row["value"])
    except json.JSONDecodeError:
        logger.warning("Invalid JSON stored for system setting %s", key)
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def set_setting_json(key: str, value: dict[str, Any], updated_by: str | None) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with db.get_core_connection() as conn:
        conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, payload, _utc_now_iso(), updated_by),
        )
        conn.commit()


def encrypt_smtp_password(password: str) -> str:
    return encrypt_secret(password)


def decrypt_smtp_password(token: str) -> str:
    return decrypt_secret(token)


def seed_default_system_settings() -> None:
    smtp_defaults = _smtp_env_defaults()
    smtp_value: dict[str, Any] = {
        "host": smtp_defaults["host"],
        "port": smtp_defaults["port"],
        "username": smtp_defaults["username"],
        "from_email": smtp_defaults["from_email"],
        "use_tls": smtp_defaults["use_tls"],
        "use_ssl": smtp_defaults["use_ssl"],
        "timeout_seconds": smtp_defaults["timeout_seconds"],
        "dev_sink": smtp_defaults["dev_sink"],
    }
    password = smtp_defaults.get("password")
    if password:
        smtp_value["password_enc"] = encrypt_smtp_password(password)

    otp_value = _otp_env_defaults()

    with db.get_core_connection() as conn:
        smtp_exists = conn.execute(
            "SELECT 1 FROM system_settings WHERE key = ?",
            (SMTP_SETTINGS_KEY,),
        ).fetchone()
        if not smtp_exists:
            conn.execute(
                "INSERT INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (
                    SMTP_SETTINGS_KEY,
                    json.dumps(smtp_value, ensure_ascii=False),
                    _utc_now_iso(),
                    None,
                ),
            )
        otp_exists = conn.execute(
            "SELECT 1 FROM system_settings WHERE key = ?",
            (OTP_EMAIL_SETTINGS_KEY,),
        ).fetchone()
        if not otp_exists:
            conn.execute(
                "INSERT INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (
                    OTP_EMAIL_SETTINGS_KEY,
                    json.dumps(otp_value, ensure_ascii=False),
                    _utc_now_iso(),
                    None,
                ),
            )
        conn.commit()


def _smtp_from_dict(payload: dict[str, Any]) -> SmtpConfig:
    defaults = _smtp_env_defaults()
    host = payload.get("host", defaults["host"])
    port = _coerce_int(payload.get("port", defaults["port"]), defaults["port"])
    username = payload.get("username", defaults["username"])
    from_email = payload.get("from_email", defaults["from_email"]) or _DEFAULT_FROM_EMAIL
    use_tls = _coerce_bool(payload.get("use_tls", defaults["use_tls"]), defaults["use_tls"])
    use_ssl = _coerce_bool(payload.get("use_ssl", defaults["use_ssl"]), defaults["use_ssl"])
    timeout_seconds = _coerce_int(
        payload.get("timeout_seconds", defaults["timeout_seconds"]),
        defaults["timeout_seconds"],
    )
    dev_sink = _coerce_bool(payload.get("dev_sink", defaults["dev_sink"]), defaults["dev_sink"])
    password_enc = payload.get("password_enc")
    password: str | None = None
    if password_enc:
        try:
            password = decrypt_smtp_password(str(password_enc))
        except Exception:
            logger.exception("Failed to decrypt SMTP password.")
            password = None
    return SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout_seconds=timeout_seconds,
        dev_sink=dev_sink,
    )


def get_email_smtp_config() -> SmtpConfig:
    raw = get_setting_json(SMTP_SETTINGS_KEY)
    if raw is None:
        env_defaults = _smtp_env_defaults()
        return SmtpConfig(
            host=env_defaults["host"],
            port=env_defaults["port"],
            username=env_defaults["username"],
            password=env_defaults["password"],
            from_email=env_defaults["from_email"],
            use_tls=env_defaults["use_tls"],
            use_ssl=env_defaults["use_ssl"],
            timeout_seconds=env_defaults["timeout_seconds"],
            dev_sink=env_defaults["dev_sink"],
        )
    return _smtp_from_dict(raw)


def get_email_smtp_config_state() -> tuple[SmtpConfig, bool]:
    raw = get_setting_json(SMTP_SETTINGS_KEY)
    if raw is None:
        env_defaults = _smtp_env_defaults()
        config = SmtpConfig(
            host=env_defaults["host"],
            port=env_defaults["port"],
            username=env_defaults["username"],
            password=env_defaults["password"],
            from_email=env_defaults["from_email"],
            use_tls=env_defaults["use_tls"],
            use_ssl=env_defaults["use_ssl"],
            timeout_seconds=env_defaults["timeout_seconds"],
            dev_sink=env_defaults["dev_sink"],
        )
        return config, bool(env_defaults.get("password"))
    return _smtp_from_dict(raw), bool(raw.get("password_enc"))


def _otp_from_dict(payload: dict[str, Any]) -> OtpEmailConfig:
    defaults = _otp_env_defaults()
    return OtpEmailConfig(
        ttl_minutes=_coerce_int(payload.get("ttl_minutes", defaults["ttl_minutes"]), defaults["ttl_minutes"]),
        code_length=_coerce_int(payload.get("code_length", defaults["code_length"]), defaults["code_length"]),
        max_attempts=_coerce_int(payload.get("max_attempts", defaults["max_attempts"]), defaults["max_attempts"]),
        resend_cooldown_seconds=_coerce_int(
            payload.get("resend_cooldown_seconds", defaults["resend_cooldown_seconds"]),
            defaults["resend_cooldown_seconds"],
        ),
        rate_limit_per_hour=_coerce_int(
            payload.get("rate_limit_per_hour", defaults["rate_limit_per_hour"]),
            defaults["rate_limit_per_hour"],
        ),
        allow_insecure_dev=_coerce_bool(
            payload.get("allow_insecure_dev", defaults["allow_insecure_dev"]),
            defaults["allow_insecure_dev"],
        ),
    )


def get_email_otp_config() -> OtpEmailConfig:
    raw = get_setting_json(OTP_EMAIL_SETTINGS_KEY)
    if raw is None:
        defaults = _otp_env_defaults()
        return OtpEmailConfig(**defaults)
    return _otp_from_dict(raw)

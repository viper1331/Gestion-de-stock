"""SMTP email delivery helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from email.message import EmailMessage
import smtplib

logger = logging.getLogger(__name__)

_DEV_SINK_PATH = Path("logs") / "email_dev_sink.log"


class EmailSendError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailSettings:
    host: str | None
    port: int
    username: str | None
    password: str | None
    from_email: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int
    dev_sink: bool


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


def get_email_settings() -> EmailSettings:
    return EmailSettings(
        host=os.getenv("SMTP_HOST"),
        port=_get_int_env("SMTP_PORT", 587),
        username=os.getenv("SMTP_USERNAME"),
        password=os.getenv("SMTP_PASSWORD"),
        from_email=os.getenv("SMTP_FROM_EMAIL", "StockOps <no-reply@localhost>"),
        use_tls=_get_bool_env("SMTP_USE_TLS", True),
        use_ssl=_get_bool_env("SMTP_USE_SSL", False),
        timeout_seconds=_get_int_env("SMTP_TIMEOUT_SECONDS", 10),
        dev_sink=_get_bool_env("EMAIL_DEV_SINK", False),
    )


def _write_dev_sink(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None,
    sensitive: bool,
) -> None:
    _DEV_SINK_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    redacted_text = "[REDACTED]" if sensitive else body_text
    redacted_html = "[REDACTED]" if sensitive and body_html else body_html
    with _DEV_SINK_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] to={to_email}\n")
        handle.write(f"subject={subject}\n")
        handle.write(f"body_text={redacted_text}\n")
        if redacted_html:
            handle.write(f"body_html={redacted_html}\n")
        handle.write("---\n")


def _login_if_needed(server: smtplib.SMTP, settings: EmailSettings) -> None:
    if settings.username and settings.password:
        server.login(settings.username, settings.password)


def send_email_smtp(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    *,
    sensitive: bool = False,
) -> None:
    settings = get_email_settings()
    if settings.dev_sink:
        _write_dev_sink(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            sensitive=sensitive,
        )
        logger.info("[EMAIL] dev sink used for to=%s", to_email)
        return
    if not settings.host:
        raise EmailSendError("SMTP_HOST manquant")

    message = EmailMessage()
    message["From"] = settings.from_email
    message["To"] = to_email
    message["Subject"] = subject
    if body_html:
        message.set_content(body_text)
        message.add_alternative(body_html, subtype="html")
    else:
        message.set_content(body_text)

    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(
                settings.host,
                settings.port,
                timeout=settings.timeout_seconds,
            ) as server:
                _login_if_needed(server, settings)
                server.send_message(message)
        else:
            with smtplib.SMTP(
                settings.host,
                settings.port,
                timeout=settings.timeout_seconds,
            ) as server:
                server.ehlo()
                if settings.use_tls:
                    server.starttls()
                    server.ehlo()
                _login_if_needed(server, settings)
                server.send_message(message)
    except Exception as exc:
        logger.error("[EMAIL] SMTP send failed to=%s", to_email)
        raise EmailSendError("Échec envoi SMTP") from exc

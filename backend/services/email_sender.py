"""SMTP email delivery helpers."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from email.message import EmailMessage
from email.utils import make_msgid
import smtplib

from backend.services.system_settings import SmtpConfig, get_email_smtp_config

logger = logging.getLogger(__name__)

_DEV_SINK_PATH = Path("logs") / "email_dev_sink.log"


class EmailSendError(RuntimeError):
    pass


def _write_dev_sink(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None,
    sensitive: bool,
    reply_to: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    _DEV_SINK_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    redacted_text = "[REDACTED]" if sensitive else body_text
    redacted_html = "[REDACTED]" if sensitive and body_html else body_html
    with _DEV_SINK_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] to={to_email}\n")
        if reply_to:
            handle.write(f"reply_to={reply_to}\n")
        handle.write(f"subject={subject}\n")
        handle.write(f"body_text={redacted_text}\n")
        if redacted_html:
            handle.write(f"body_html={redacted_html}\n")
        if attachments:
            handle.write(f"attachments={len(attachments)}\n")
        handle.write("---\n")


def _login_if_needed(server: smtplib.SMTP, settings: SmtpConfig) -> None:
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
    settings = get_email_smtp_config()
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


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    *,
    reply_to: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    sensitive: bool = False,
) -> str:
    settings = get_email_smtp_config()
    if settings.dev_sink:
        _write_dev_sink(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            sensitive=sensitive,
            reply_to=reply_to,
            attachments=attachments,
        )
        logger.info("[EMAIL] dev sink used for to=%s", to_email)
        return "dev-sink"
    if not settings.host:
        raise EmailSendError("SMTP_HOST manquant")

    message = EmailMessage()
    message["From"] = settings.from_email
    message["To"] = to_email
    message["Subject"] = subject
    message_id = make_msgid()
    message["Message-ID"] = message_id
    if reply_to:
        message["Reply-To"] = reply_to
    if body_html:
        message.set_content(body_text)
        message.add_alternative(body_html, subtype="html")
    else:
        message.set_content(body_text)
    if attachments:
        for filename, content, mime_type in attachments:
            if "/" in mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = mime_type, "octet-stream"
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

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
    return message_id

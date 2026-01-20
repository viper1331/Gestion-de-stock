"""Notifications email + outbox worker."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any

from backend.core import db, models, services
from backend.services.email_sender import EmailSendError, send_email_smtp
from backend.services.system_settings import get_email_smtp_config

logger = logging.getLogger(__name__)

_DEFAULT_OUTBOX_INTERVAL_SECONDS = 3
_DEFAULT_OUTBOX_BATCH_SIZE = 20


@dataclass(frozen=True)
class OutboxRunResult:
    sent: int
    failed: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_email_delivery_available() -> bool:
    settings = get_email_smtp_config()
    return bool(settings.dev_sink or settings.host)


def _any_otp_email_enabled() -> bool:
    with db.get_users_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE otp_email_enabled = 1 LIMIT 1"
        ).fetchone()
    return bool(row)


def ensure_email_delivery_ready() -> None:
    smtp_required = os.getenv("SMTP_REQUIRED_FOR_STARTUP") == "1"
    if not _any_otp_email_enabled():
        return
    if is_email_delivery_available():
        return
    message = "SMTP non configuré: OTP e-mail indisponible."
    if smtp_required:
        raise RuntimeError(message)
    logger.error(message)


def enqueue_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    *,
    priority: int = 5,
    purpose: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        cursor = conn.execute(
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
            VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, ?)
            """,
            (
                to_email,
                subject,
                body_text,
                body_html,
                _utc_now_iso(),
                priority,
            ),
        )
        conn.commit()
    email_id = int(cursor.lastrowid)
    logger.info(
        "[EMAIL] queued id=%s to=%s subject=%s purpose=%s meta=%s",
        email_id,
        to_email,
        subject,
        purpose,
        meta,
    )
    return email_id


def build_login_otp_email(
    code: str,
    ttl_minutes: int,
    device_hint: str | None,
) -> tuple[str, str, str]:
    subject = "Votre code de connexion StockOps"
    device_line = f"\nAppareil: {device_hint}\n" if device_hint else "\n"
    body_text = (
        "Bonjour,\n\n"
        "Voici votre code à usage unique pour vous connecter à StockOps :\n\n"
        f"{code}\n\n"
        f"Ce code expire dans {ttl_minutes} minutes."
        f"{device_line}"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
    )
    body_html = (
        "<p>Bonjour,</p>"
        "<p>Voici votre code à usage unique pour vous connecter à <strong>StockOps</strong> :</p>"
        f"<p style=\"font-size: 20px; font-weight: bold;\">{code}</p>"
        f"<p>Ce code expire dans {ttl_minutes} minutes.</p>"
        f"<p>{device_hint or ''}</p>"
        "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
    )
    return subject, body_text, body_html


def enqueue_login_otp_email(
    to_email: str,
    code: str,
    ttl_minutes: int,
    device_hint: str | None,
) -> None:
    subject, body_text, body_html = build_login_otp_email(code, ttl_minutes, device_hint)
    enqueue_email(to_email, subject, body_text, body_html, priority=1)


def build_purchase_order_email(
    purchase_order: models.PurchaseOrderDetail,
    site: models.SiteInfo,
    user: models.User | None,
) -> tuple[str, str, str]:
    site_label = site.display_name or site.site_key
    subject = f"Bon de commande #{purchase_order.id} - {site_label}"
    supplier_name = purchase_order.supplier_name or "votre équipe"
    sender_label = user.display_name or user.username if user else "notre équipe"
    sender_email = user.email if user and user.email else None
    sender_contact = (
        f"{sender_label} <{sender_email}>" if sender_email else sender_label
    )
    intro = f"Bonjour {supplier_name},"
    body_text = (
        f"{intro}\n\n"
        f"Veuillez trouver ci-joint le bon de commande #{purchase_order.id} "
        f"pour le site {site_label}.\n\n"
        f"Expéditeur : {sender_contact}\n\n"
        f"Cordialement,\n{sender_label}\n"
    )
    body_html = (
        f"<p>{intro}</p>"
        f"<p>Veuillez trouver ci-joint le bon de commande <strong>#{purchase_order.id}</strong> "
        f"pour le site <strong>{site_label}</strong>.</p>"
        f"<p>Expéditeur : {sender_contact}</p>"
        f"<p>Cordialement,<br />{sender_label}</p>"
    )
    return subject, body_text, body_html


def run_outbox_once(max_batch: int | None = None) -> OutboxRunResult:
    services.ensure_database_ready()
    batch_size = max_batch or _DEFAULT_OUTBOX_BATCH_SIZE
    sent = 0
    failed = 0
    with db.get_core_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, to_email, subject, body_text, body_html, send_attempts
            FROM email_outbox
            WHERE sent_at IS NULL
            ORDER BY priority ASC, id ASC
            LIMIT ?
            """,
            (batch_size,),
        ).fetchall()
        for row in rows:
            try:
                send_email_smtp(
                    row["to_email"],
                    row["subject"],
                    row["body_text"],
                    row["body_html"],
                    sensitive=True,
                )
            except EmailSendError as exc:
                failed += 1
                attempts = int(row["send_attempts"]) + 1
                conn.execute(
                    """
                    UPDATE email_outbox
                    SET send_attempts = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (attempts, str(exc), row["id"]),
                )
                logger.warning(
                    "[EMAIL] failed id=%s to=%s attempts=%s error=%s",
                    row["id"],
                    row["to_email"],
                    attempts,
                    str(exc),
                )
                continue
            sent += 1
            conn.execute(
                """
                UPDATE email_outbox
                SET sent_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (_utc_now_iso(), row["id"]),
            )
            logger.info("[EMAIL] sent id=%s to=%s", row["id"], row["to_email"])
    return OutboxRunResult(sent=sent, failed=failed)


def purge_email_tables() -> None:
    services.ensure_database_ready()
    now = _utc_now()
    challenge_cutoff = (now - timedelta(days=7)).isoformat()
    outbox_cutoff = (now - timedelta(days=30)).isoformat()
    with db.get_core_connection() as conn:
        conn.execute(
            "DELETE FROM otp_email_challenges WHERE expires_at < ?",
            (challenge_cutoff,),
        )
        conn.execute(
            "DELETE FROM email_outbox WHERE sent_at IS NOT NULL AND sent_at < ?",
            (outbox_cutoff,),
        )
        conn.commit()


async def _outbox_loop(stop_event: asyncio.Event, interval_seconds: int) -> None:
    while not stop_event.is_set():
        try:
            result = await asyncio.to_thread(run_outbox_once)
        except Exception as exc:
            logger.error("[EMAIL] outbox worker failure", exc_info=exc)
            delay = min(interval_seconds * 2, interval_seconds + 5)
        else:
            delay = interval_seconds
            if result.failed:
                delay = min(interval_seconds * 2, interval_seconds + 5)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue


def start_outbox_worker(app: Any) -> None:
    if getattr(app.state, "outbox_worker_task", None):
        return
    interval_seconds = _get_int_env("OUTBOX_WORKER_INTERVAL_SECONDS", _DEFAULT_OUTBOX_INTERVAL_SECONDS)
    stop_event = asyncio.Event()
    app.state.outbox_worker_stop = stop_event
    app.state.outbox_worker_task = asyncio.create_task(_outbox_loop(stop_event, interval_seconds))
    logger.info("[EMAIL] outbox worker started interval=%ss", interval_seconds)


def stop_outbox_worker(app: Any) -> None:
    stop_event: asyncio.Event | None = getattr(app.state, "outbox_worker_stop", None)
    task: asyncio.Task | None = getattr(app.state, "outbox_worker_task", None)
    if not stop_event or not task:
        return
    stop_event.set()


async def shutdown_outbox_worker(app: Any) -> None:
    stop_event: asyncio.Event | None = getattr(app.state, "outbox_worker_stop", None)
    task: asyncio.Task | None = getattr(app.state, "outbox_worker_task", None)
    if not stop_event or not task:
        return
    stop_event.set()
    await task
    logger.info("[EMAIL] outbox worker stopped")


def on_user_approved(user: models.User, modules: list[str] | None = None) -> None:
    if not user.email:
        logger.warning(
            "[EMAIL] user_approved missing email user=%s",
            user.username,
        )
        return
    name = user.display_name or user.username
    modules_line = ""
    if modules:
        modules_list = "\n".join(f"- {module}" for module in modules)
        modules_line = f"\nModules accessibles :\n{modules_list}\n"
    subject = "Compte validé – Gestion Stock Pro"
    body_text = (
        f"Bonjour {name},\n\n"
        "Votre compte a été validé par un administrateur.\n"
        f"{modules_line}\n"
        "L'authentification à deux facteurs pourra être activée selon la politique du site.\n"
    )
    enqueue_email(
        to_email=user.email,
        subject=subject,
        body_text=body_text,
        purpose="user_approved",
        meta={"user_id": user.id, "username": user.username, "modules": modules or []},
    )


def enqueue_password_reset(
    email: str,
    reset_token: str,
    metadata: dict[str, object] | None = None,
) -> None:
    ttl_minutes: int | None = None
    metadata = metadata or {}
    raw_ttl = metadata.get("ttl_minutes")
    if isinstance(raw_ttl, int):
        ttl_minutes = raw_ttl
    expires_at = metadata.get("expires_at")
    if ttl_minutes is None and isinstance(expires_at, str):
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            ttl_minutes = max(1, int((expires - _utc_now()).total_seconds() / 60))
        except ValueError:
            ttl_minutes = None
    ttl_line = f"Ce code expire dans {ttl_minutes} minutes.\n" if ttl_minutes else ""
    subject = "Code de vérification – Réinitialisation du mot de passe"
    body_text = (
        "Bonjour,\n\n"
        "Voici votre code de vérification pour réinitialiser votre mot de passe :\n\n"
        f"{reset_token}\n\n"
        f"{ttl_line}"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail et contactez un administrateur."
    )
    enqueue_email(
        to_email=email,
        subject=subject,
        body_text=body_text,
        purpose="password_reset",
        meta={
            "email": email,
            "ttl_minutes": ttl_minutes,
            "kind": "otp",
        },
    )

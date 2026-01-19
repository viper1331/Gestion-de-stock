"""Notifications hooks (stub)."""
from __future__ import annotations

import logging

from backend.core import models

logger = logging.getLogger(__name__)


def on_user_approved(user: models.User, modules: list[str] | None = None) -> None:
    logger.info(
        "[NOTIFY] user_approved queued (noop) user=%s email=%s modules=%s",
        user.username,
        user.email,
        modules,
    )


def enqueue_password_reset(
    email: str,
    reset_token: str,
    metadata: dict[str, object] | None = None,
) -> None:
    logger.info(
        "[NOTIFY] password_reset queued (noop) email=%s metadata=%s",
        email,
        metadata,
    )

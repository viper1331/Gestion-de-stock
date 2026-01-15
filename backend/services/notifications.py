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

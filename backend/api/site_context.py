"""Middleware de sélection du site pour les requêtes API."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core import db, security, services, sites

logger = logging.getLogger(__name__)


class SiteContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        user = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = security.decode_token(token)
                username = payload.get("sub")
                if username:
                    user = services.get_user(username)
            except Exception as exc:  # pragma: no cover - invalid tokens handled elsewhere
                logger.debug("[SITE] Token decode failed: %s", exc)
        resolved_site = sites.resolve_site_key(user, request.headers.get("X-Site-Key"))
        token = db.set_current_site(resolved_site)
        try:
            try:
                response = await call_next(request)
            except sqlite3.OperationalError as exc:
                if services.is_missing_table_error(exc) and not getattr(
                    request.state, "db_autoretry", False
                ):
                    request.state.db_autoretry = True
                    logger.warning(
                        "[SITE] Missing table detected for %s; reapplying migrations.",
                        resolved_site,
                    )
                    services.ensure_site_database_ready(resolved_site)
                    response = await call_next(request)
                else:
                    raise
        finally:
            db.reset_current_site(token)
        return response

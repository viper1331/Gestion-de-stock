"""Middleware de sélection du site pour les requêtes API."""
from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core import db, security, services, sites

logger = logging.getLogger(__name__)


class SiteContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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
            response = await call_next(request)
        finally:
            db.reset_current_site(token)
        return response

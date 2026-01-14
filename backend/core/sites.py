"""Gestion des sites et routage multi-base."""
from __future__ import annotations

import logging
from typing import Iterable

from backend.core import db, models

logger = logging.getLogger(__name__)


def normalize_site_key(site_key: str | None) -> str | None:
    if not site_key:
        return None
    normalized = site_key.strip().upper()
    if normalized not in db.SITE_KEYS:
        raise ValueError(f"Site inconnu: {site_key}")
    return normalized


def list_sites() -> list[models.SiteInfo]:
    with db.get_core_connection() as conn:
        rows = conn.execute(
            "SELECT site_key, display_name, db_path, is_active FROM sites ORDER BY site_key"
        ).fetchall()
    return [
        models.SiteInfo(
            site_key=row["site_key"],
            display_name=row["display_name"],
            db_path=row["db_path"],
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]


def get_user_site_assignment(username: str) -> str | None:
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT site_key FROM user_site_assignments WHERE username = ?",
            (username,),
        ).fetchone()
    if row:
        return row["site_key"]
    return None


def set_user_site_assignment(username: str, site_key: str) -> None:
    normalized = normalize_site_key(site_key)
    if not normalized:
        return
    with db.get_core_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_site_assignments (username, site_key)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET site_key = excluded.site_key
            """,
            (username, normalized),
        )
        conn.commit()


def get_user_site_override(username: str) -> str | None:
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT site_key FROM user_site_overrides WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return None
    return row["site_key"]


def set_user_site_override(username: str, site_key: str | None) -> None:
    normalized = normalize_site_key(site_key) if site_key else None
    with db.get_core_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_site_overrides (username, site_key)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET
              site_key = excluded.site_key,
              updated_at = CURRENT_TIMESTAMP
            """,
            (username, normalized),
        )
        conn.commit()


def resolve_site_key(
    user: models.User | None,
    header_site_key: str | None,
) -> str:
    if user and user.role == "admin" and header_site_key:
        try:
            return normalize_site_key(header_site_key) or db.DEFAULT_SITE_KEY
        except ValueError:
            logger.warning("[SITE] Invalid header site key: %s", header_site_key)
    if user and user.role == "admin":
        override = get_user_site_override(user.username)
        if override:
            return override
    if user:
        assigned = get_user_site_assignment(user.username)
        if assigned:
            return assigned
    return db.DEFAULT_SITE_KEY


def resolve_site_context(
    user: models.User | None,
    header_site_key: str | None,
    sites: Iterable[models.SiteInfo] | None = None,
) -> models.SiteContext:
    assigned_site = db.DEFAULT_SITE_KEY
    override_site = None
    if user:
        assigned_site = get_user_site_assignment(user.username) or db.DEFAULT_SITE_KEY
        if user.role == "admin":
            override_site = get_user_site_override(user.username)
    active_site = resolve_site_key(user, header_site_key)
    return models.SiteContext(
        assigned_site_key=assigned_site,
        active_site_key=active_site,
        override_site_key=override_site,
        sites=list(sites) if sites is not None else None,
    )

"""Gestion des sites et routage multi-base."""
from __future__ import annotations

import logging
import re
from typing import Iterable

from backend.core import db, models

logger = logging.getLogger(__name__)

_SITE_KEY_ALIASES = {
    "ST_ELOIS": "ST_ELOIS",
    "ST-ELOIS": "ST_ELOIS",
    "ST ELOIS": "ST_ELOIS",
    "SAINT_ELOIS": "ST_ELOIS",
    "SAINT-ELOIS": "ST_ELOIS",
    "SAINT ELOIS": "ST_ELOIS",
    "CENTRAL_ENTITY": "CENTRAL_ENTITY",
    "CENTRAL ENTITY": "CENTRAL_ENTITY",
    "ENTITE_CENTRALE": "CENTRAL_ENTITY",
    "ENTITE CENTRALE": "CENTRAL_ENTITY",
    "JLL": "JLL",
    "GSM": "GSM",
}


def normalize_site_key(site_key: str | None) -> str | None:
    if not site_key:
        return None
    stripped = site_key.strip()
    if not stripped:
        return None
    normalized = re.sub(r"[\s\-]+", "_", stripped).upper()
    mapped = _SITE_KEY_ALIASES.get(normalized)
    if mapped:
        return mapped
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
    with db.get_users_connection() as conn:
        try:
            row = conn.execute(
                "SELECT site_key FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        except Exception:
            return None
    if row and row["site_key"]:
        return row["site_key"]
    return None


def set_user_site_assignment(username: str, site_key: str) -> None:
    normalized = normalize_site_key(site_key)
    if not normalized:
        return
    with db.get_users_connection() as conn:
        conn.execute(
            "UPDATE users SET site_key = ? WHERE username = ?",
            (normalized, username),
        )
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
    with db.get_users_connection() as conn:
        try:
            row = conn.execute(
                "SELECT admin_active_site_key FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        except Exception:
            row = None
    if row and row["admin_active_site_key"]:
        return row["admin_active_site_key"]
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT site_key FROM user_site_overrides WHERE username = ?",
            (username,),
        ).fetchone()
    if row:
        return row["site_key"]
    return None


def set_user_site_override(username: str, site_key: str | None) -> None:
    normalized = normalize_site_key(site_key) if site_key else None
    with db.get_users_connection() as conn:
        conn.execute(
            "UPDATE users SET admin_active_site_key = ? WHERE username = ?",
            (normalized, username),
        )
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
        assigned = user.site_key or get_user_site_assignment(user.username)
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
        assigned_site = user.site_key or get_user_site_assignment(user.username) or db.DEFAULT_SITE_KEY
        if user.role == "admin":
            override_site = get_user_site_override(user.username)
    active_site = resolve_site_key(user, header_site_key)
    return models.SiteContext(
        assigned_site_key=assigned_site,
        active_site_key=active_site,
        override_site_key=override_site,
        sites=list(sites) if sites is not None else None,
    )

"""Gestion des paramètres de sauvegarde automatique."""
from __future__ import annotations

import sqlite3

from backend.core import db, models
from backend.services.backup_manager import MAX_BACKUP_FILES

GLOBAL_BACKUP_KEY = "GLOBAL"

DEFAULT_BACKUP_INTERVAL_MINUTES = 60
DEFAULT_BACKUP_RETENTION_COUNT = MAX_BACKUP_FILES
MAX_BACKUP_INTERVAL_MINUTES = 60 * 24 * 7


def _ensure_backup_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS backup_settings (
            site_key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            interval_minutes INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_INTERVAL_MINUTES},
            retention_count INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_RETENTION_COUNT},
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
    return "no such table" in str(exc).lower()


def load_backup_settings_from_db(site_key: str) -> models.BackupSettings:
    normalized_key = GLOBAL_BACKUP_KEY
    with db.get_core_connection() as conn:
        try:
            row = conn.execute(
                """
                SELECT enabled, interval_minutes, retention_count
                FROM backup_settings
                WHERE site_key = ?
                """,
                (normalized_key,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if not _is_missing_table_error(exc):
                raise
            _ensure_backup_settings_table(conn)
            row = conn.execute(
                """
                SELECT enabled, interval_minutes, retention_count
                FROM backup_settings
                WHERE site_key = ?
                """,
                (normalized_key,),
            ).fetchone()
    if row is None:
        return models.BackupSettings(
            enabled=False,
            interval_minutes=DEFAULT_BACKUP_INTERVAL_MINUTES,
            retention_count=DEFAULT_BACKUP_RETENTION_COUNT,
        )
    return models.BackupSettings(
        enabled=bool(row["enabled"]),
        interval_minutes=int(row["interval_minutes"]),
        retention_count=int(row["retention_count"]),
    )


def save_backup_settings(site_key: str, settings: models.BackupSettings) -> None:
    normalized_key = GLOBAL_BACKUP_KEY
    with db.get_core_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO backup_settings (
                    site_key,
                    enabled,
                    interval_minutes,
                    retention_count,
                    updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(site_key) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_minutes = excluded.interval_minutes,
                    retention_count = excluded.retention_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_key,
                    1 if settings.enabled else 0,
                    settings.interval_minutes,
                    settings.retention_count,
                ),
            )
        except sqlite3.OperationalError as exc:
            if not _is_missing_table_error(exc):
                raise
            _ensure_backup_settings_table(conn)
            conn.execute(
                """
                INSERT INTO backup_settings (
                    site_key,
                    enabled,
                    interval_minutes,
                    retention_count,
                    updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(site_key) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_minutes = excluded.interval_minutes,
                    retention_count = excluded.retention_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_key,
                    1 if settings.enabled else 0,
                    settings.interval_minutes,
                    settings.retention_count,
                ),
            )


def get_backup_settings(site_key: str) -> models.BackupSettings:
    return load_backup_settings_from_db(site_key)


def set_backup_settings(site_key: str, settings: models.BackupSettings) -> None:
    save_backup_settings(site_key, settings)

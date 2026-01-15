"""Gestion des paramètres de sauvegarde automatique."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.core import db, models
from backend.services.backup_manager import MAX_BACKUP_FILES

DEFAULT_BACKUP_INTERVAL_MINUTES = 60
DEFAULT_BACKUP_RETENTION_COUNT = MAX_BACKUP_FILES
MAX_BACKUP_INTERVAL_MINUTES = 60 * 24 * 7


def load_backup_settings_from_db(site_key: str) -> models.BackupSettings:
    with db.get_stock_connection(site_key) as conn:
        row = conn.execute(
            """
            SELECT enabled, interval_minutes, retention_count
            FROM backup_settings
            WHERE id = 1
            """
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
    updated_at = datetime.now(timezone.utc).isoformat()
    with db.get_stock_connection(site_key) as conn:
        conn.execute(
            """
            INSERT INTO backup_settings (id, enabled, interval_minutes, retention_count, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                enabled = excluded.enabled,
                interval_minutes = excluded.interval_minutes,
                retention_count = excluded.retention_count,
                updated_at = excluded.updated_at
            """,
            (
                1 if settings.enabled else 0,
                settings.interval_minutes,
                settings.retention_count,
                updated_at,
            ),
        )

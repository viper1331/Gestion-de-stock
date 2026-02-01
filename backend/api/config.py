"""Routes de gestion de la configuration."""
from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models
from backend.services import system_settings

router = APIRouter()
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"

_HOMEPAGE_ALLOWED_KEYS: tuple[str, ...] = (
    "title",
    "subtitle",
    "welcome_message",
    "primary_link_label",
    "primary_link_path",
    "secondary_link_label",
    "secondary_link_path",
    "announcement",
    "focus_1_label",
    "focus_1_description",
    "focus_2_label",
    "focus_2_description",
    "focus_3_label",
    "focus_3_description",
)


@router.get("/", response_model=list[models.ConfigEntry])
async def read_config(_: models.User = Depends(get_current_user)) -> list[models.ConfigEntry]:
    parser = ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    entries: list[models.ConfigEntry] = []
    for section in parser.sections():
        for key, value in parser.items(section):
            entries.append(models.ConfigEntry(section=section, key=key, value=value))
    return entries


@router.post("/", status_code=204)
async def write_config(entry: models.ConfigEntry, user: models.User = Depends(get_current_user)) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    parser = ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    if not parser.has_section(entry.section):
        parser.add_section(entry.section)
    parser.set(entry.section, entry.key, entry.value)
    with CONFIG_PATH.open("w", encoding="utf-8") as configfile:
        parser.write(configfile)


def _validate_homepage_entry(entry: models.ConfigEntry) -> None:
    if entry.section != "homepage":
        raise HTTPException(status_code=400, detail="Section de configuration invalide")
    if entry.key not in _HOMEPAGE_ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail="Clé de configuration inconnue")


@router.get("/homepage/personal", response_model=list[models.ConfigEntry])
async def read_personal_homepage_config(
    user: models.User = Depends(get_current_user),
) -> list[models.ConfigEntry]:
    with db.get_users_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_homepage_config WHERE user_id = ? ORDER BY key",
            (user.id,),
        ).fetchall()
    return [models.ConfigEntry(section="homepage", key=row["key"], value=row["value"]) for row in rows]


@router.post("/homepage/personal", status_code=204)
async def write_personal_homepage_config(
    entry: models.ConfigEntry,
    user: models.User = Depends(get_current_user),
) -> None:
    _validate_homepage_entry(entry)
    value = entry.value.strip()
    with db.get_users_connection() as conn:
        if value:
            conn.execute(
                """
                INSERT INTO user_homepage_config (user_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
                """,
                (user.id, entry.key, value),
            )
        else:
            conn.execute(
                "DELETE FROM user_homepage_config WHERE user_id = ? AND key = ?",
                (user.id, entry.key),
            )


@router.get("/qol-settings", response_model=models.QolSettings)
async def read_qol_settings(_: models.User = Depends(get_current_user)) -> models.QolSettings:
    settings = system_settings.get_qol_settings()
    return models.QolSettings(
        timezone=settings.timezone,
        date_format=settings.date_format,
        auto_archive_days=settings.auto_archive_days,
        note_preview_length=settings.note_preview_length,
    )


@router.get("/feature-flags", response_model=models.FeatureFlags)
async def read_feature_flags(_: models.User = Depends(get_current_user)) -> models.FeatureFlags:
    return models.FeatureFlags(feature_ari_enabled=system_settings.get_feature_ari_enabled())

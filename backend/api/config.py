"""Routes de gestion de la configuration."""
from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models

router = APIRouter()
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


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
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    parser = ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    if not parser.has_section(entry.section):
        parser.add_section(entry.section)
    parser.set(entry.section, entry.key, entry.value)
    with CONFIG_PATH.open("w", encoding="utf-8") as configfile:
        parser.write(configfile)

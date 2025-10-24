"""Endpoint de sauvegarde des bases."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copy2, make_archive

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import db, models

router = APIRouter()
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)


@router.get("/", response_class=FileResponse)
async def backup_databases(_: models.User = Depends(get_current_user)) -> FileResponse:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = BACKUP_DIR / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    stock_path = archive_dir / "stock.db"
    users_path = archive_dir / "users.db"
    copy2(db.STOCK_DB_PATH, stock_path)
    copy2(db.USERS_DB_PATH, users_path)
    archive_path = make_archive(str(archive_dir), "zip", archive_dir)
    return FileResponse(archive_path, filename=f"backup-{timestamp}.zip")

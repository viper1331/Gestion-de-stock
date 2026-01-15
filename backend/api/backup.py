"""Endpoints de gestion des sauvegardes des bases."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import models
from backend.services.backup_manager import (
    BackupImportError,
    create_backup_archive,
    restore_backup_from_zip,
)

router = APIRouter()


@router.get("/", response_class=FileResponse)
async def backup_databases(_: models.User = Depends(get_current_user)) -> FileResponse:
    archive_path = create_backup_archive()
    return FileResponse(archive_path, filename=archive_path.name)


@router.post("/import", status_code=204)
async def import_backup(
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")

    with TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "import.zip"
        with target.open("wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
        await file.close()

        if target.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fichier de sauvegarde vide",
            )

        try:
            restore_backup_from_zip(target)
        except BackupImportError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except OSError as exc:  # pragma: no cover - erreurs disque imprévisibles
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible d'importer la sauvegarde",
            ) from exc


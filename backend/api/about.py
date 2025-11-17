from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.auth import get_current_user
from backend.core import models
from backend.services import update_service

router = APIRouter()


_SUMMARY = (
    "Gestion Stock Pro 2.0 modernise la gestion des stocks, des dotations et des inventaires "
    "spécialisés en combinant un backend FastAPI, une interface web React et un client desktop Tauri. "
    "L'application centralise les flux d'articles, les rapports et les permissions pour les équipes opérationnelles."
)

_LICENSE_PATH = Path(__file__).resolve().parents[2] / "LICENSE"


def _read_license() -> str:
    if not _LICENSE_PATH.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Fichier de licence introuvable")
    try:
        return _LICENSE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Lecture de la licence impossible") from exc


def _build_version(status: models.UpdateStatus) -> models.AboutVersionInfo:
    commit = status.last_deployed_sha or status.current_commit

    if status.last_deployed_pull and status.last_deployed_sha:
        label = f"Déploiement PR #{status.last_deployed_pull} ({status.last_deployed_sha[:7]})"
    elif commit:
        label = f"Commit {commit[:7]} sur {status.branch}"
    else:
        label = "Version inconnue"

    return models.AboutVersionInfo(
        label=label,
        branch=status.branch,
        last_update=status.last_deployed_at,
        source_commit=commit,
        pending_update=status.pending_update,
    )


@router.get("", response_model=models.AboutInfo)
async def get_about(user: models.User = Depends(get_current_user)) -> models.AboutInfo:
    status_data = await update_service.get_status()
    status = models.UpdateStatus.model_validate(status_data.to_dict())

    return models.AboutInfo(
        summary=_SUMMARY,
        license=_read_license(),
        version=_build_version(status),
    )

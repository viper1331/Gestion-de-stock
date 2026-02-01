"""Routes pour la gestion des sessions ARI."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import get_current_user
from backend.core import models, services
from backend.services import system_settings

router = APIRouter()

MODULE_KEY = "ari"


def _require_permission(user: models.User, *, action: str) -> None:
    if services.has_module_access(user, MODULE_KEY, action=action):
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_feature_enabled() -> None:
    if system_settings.get_feature_ari_enabled():
        return
    raise HTTPException(status_code=404, detail="Module indisponible")


@router.get("/sessions", response_model=list[models.AriSession])
async def list_ari_sessions(
    user: models.User = Depends(get_current_user),
) -> list[models.AriSession]:
    _require_feature_enabled()
    _require_permission(user, action="view")
    return services.list_ari_sessions()


@router.post("/sessions", response_model=models.AriSession, status_code=201)
async def create_ari_session(
    payload: models.AriSessionCreate,
    user: models.User = Depends(get_current_user),
) -> models.AriSession:
    _require_feature_enabled()
    _require_permission(user, action="edit")
    return services.create_ari_session(payload, created_by=user.username)


@router.get("/sessions/{session_id}", response_model=models.AriSession)
async def get_ari_session(
    session_id: int,
    user: models.User = Depends(get_current_user),
) -> models.AriSession:
    _require_feature_enabled()
    _require_permission(user, action="view")
    try:
        return services.get_ari_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/measurements", response_model=list[models.AriMeasurement])
async def list_ari_measurements(
    session_id: int,
    user: models.User = Depends(get_current_user),
) -> list[models.AriMeasurement]:
    _require_feature_enabled()
    _require_permission(user, action="view")
    return services.list_ari_measurements(session_id)


@router.post("/sessions/{session_id}/measurements", response_model=list[models.AriMeasurement])
async def create_ari_measurements(
    session_id: int,
    payload: list[models.AriMeasurementCreate],
    user: models.User = Depends(get_current_user),
) -> list[models.AriMeasurement]:
    _require_feature_enabled()
    _require_permission(user, action="edit")
    try:
        return services.create_ari_measurements(session_id, payload, created_by=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stats", response_model=models.AriStats)
async def get_ari_stats(
    user: models.User = Depends(get_current_user),
) -> models.AriStats:
    _require_feature_enabled()
    _require_permission(user, action="view")
    return services.get_ari_stats()


@router.get("/sessions/{session_id}/export/pdf")
async def export_ari_session_pdf(
    session_id: int,
    user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    _require_feature_enabled()
    _require_permission(user, action="view")
    try:
        pdf_bytes = services.generate_ari_session_pdf(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=ari_session_{session_id}.pdf"},
    )

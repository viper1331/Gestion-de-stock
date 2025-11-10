"""Routes pour la mise à jour du serveur depuis GitHub."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.auth import get_current_user
from backend.core import models
from backend.services import update_service

router = APIRouter()


def _ensure_admin(user: models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")


@router.get("/status", response_model=models.UpdateStatus)
async def get_update_status(user: models.User = Depends(get_current_user)) -> models.UpdateStatus:
    _ensure_admin(user)
    try:
        status_data = await update_service.get_status()
    except update_service.UpdateConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except update_service.UpdateError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return models.UpdateStatus.model_validate(status_data.to_dict())


@router.post("/apply", response_model=models.UpdateApplyResponse)
async def apply_update(user: models.User = Depends(get_current_user)) -> models.UpdateApplyResponse:
    _ensure_admin(user)
    try:
        updated, status_data = await update_service.apply_latest_update()
    except update_service.UpdateConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except update_service.UpdateError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return models.UpdateApplyResponse(updated=updated, status=models.UpdateStatus.model_validate(status_data.to_dict()))

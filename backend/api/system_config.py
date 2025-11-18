"""Routes d'administration de la configuration système."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import get_current_user
from backend.core import models
from backend.core.system_config import (
    SystemConfig,
    get_config,
    rebuild_cors_middleware,
    save_config,
)

router = APIRouter()


@router.get("/config", response_model=SystemConfig)
async def read_system_config(user: models.User = Depends(get_current_user)) -> SystemConfig:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return get_config()


@router.post("/config", response_model=SystemConfig)
async def update_system_config(
    payload: SystemConfig,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> SystemConfig:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    config = save_config(payload)
    rebuild_cors_middleware(request.app)
    return config

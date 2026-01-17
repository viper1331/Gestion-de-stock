"""Routes d'administration de la configuration système."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.auth import get_current_user
from backend.core import models
from backend.core.system_config import (
    SystemConfig,
    get_config,
    rebuild_cors_middleware,
    save_config,
)

router = APIRouter()


class PublicSystemConfig(BaseModel):
    backend_url: str | None = Field(default=None)
    backend_url_lan: str | None = Field(default=None)
    backend_url_public: str | None = Field(default=None)
    frontend_url: str
    network_mode: str
    idle_logout_minutes: int = Field(60, ge=0, le=1440)
    logout_on_close: bool = False


@router.get("/public-config", response_model=PublicSystemConfig)
async def read_public_config() -> PublicSystemConfig:
    config = get_config()
    return PublicSystemConfig(
        backend_url=str(config.backend_url) if config.backend_url else None,
        backend_url_lan=str(config.backend_url_lan) if config.backend_url_lan else None,
        backend_url_public=str(config.backend_url_public) if config.backend_url_public else None,
        frontend_url=str(config.frontend_url),
        network_mode=config.network_mode,
        idle_logout_minutes=config.security.idle_logout_minutes,
        logout_on_close=config.security.logout_on_close,
    )


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

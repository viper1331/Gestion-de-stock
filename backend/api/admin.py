from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models
from backend.services.debug_service import load_debug_config, save_debug_config

router = APIRouter()


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return user


@router.get("/debug-config", response_model=models.DebugConfig)
def get_debug_config(user: models.User = Depends(require_admin)):
    return load_debug_config()


@router.put("/debug-config", response_model=models.DebugConfig)
def update_debug_config(cfg: models.DebugConfig, user: models.User = Depends(require_admin)):
    save_debug_config(cfg.model_dump())
    return cfg

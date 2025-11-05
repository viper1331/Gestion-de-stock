"""Routes de génération de codes-barres."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import models, services
from backend.services import barcode as barcode_service

router = APIRouter()

MODULE_KEY = "clothing"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.post("/generate/{sku}")
async def generate_barcode(
    sku: str, user: models.User = Depends(get_current_user)
) -> FileResponse:
    _require_permission(user, action="edit")
    path = barcode_service.generate_barcode_png(sku)
    if not path:
        raise HTTPException(status_code=500, detail="Échec de la génération du code-barres")
    return FileResponse(path, filename=f"{sku}.png", media_type="image/png")


@router.delete("/generate/{sku}")
async def delete_barcode(sku: str, user: models.User = Depends(get_current_user)) -> None:
    _require_permission(user, action="edit")
    barcode_service.delete_barcode_png(sku)

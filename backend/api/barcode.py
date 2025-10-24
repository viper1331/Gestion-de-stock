"""Routes de génération de codes-barres."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import models
from backend.services import barcode as barcode_service

router = APIRouter()


@router.post("/generate/{sku}")
async def generate_barcode(sku: str, _: models.User = Depends(get_current_user)) -> FileResponse:
    path = barcode_service.generate_barcode_png(sku)
    if not path:
        raise HTTPException(status_code=500, detail="Failed to generate barcode")
    return FileResponse(path, filename=f"{sku}.png", media_type="image/png")


@router.delete("/generate/{sku}")
async def delete_barcode(sku: str, _: models.User = Depends(get_current_user)) -> None:
    barcode_service.delete_barcode_png(sku)

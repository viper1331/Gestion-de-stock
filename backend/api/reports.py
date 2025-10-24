"""Routes dédiées aux rapports."""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/low-stock", response_model=list[models.LowStockReport])
async def low_stock(threshold: int = 0, _: models.User = Depends(get_current_user)) -> list[models.LowStockReport]:
    return services.list_low_stock(threshold)


@router.get("/export/csv")
async def export_csv(_: models.User = Depends(get_current_user)) -> FileResponse:
    with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        path = Path(tmp.name)
    services.export_items_to_csv(path)
    return FileResponse(path, filename="inventaire.csv", media_type="text/csv")

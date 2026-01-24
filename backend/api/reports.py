"""Routes dédiées aux rapports."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "reports"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/low-stock", response_model=list[models.LowStockReport])
async def low_stock(
    threshold: int = 0, user: models.User = Depends(get_current_user)
) -> list[models.LowStockReport]:
    _require_permission(user, action="view")
    return services.list_low_stock(threshold)


@router.get("/overview", response_model=models.ReportOverview)
async def overview(
    module: str = Query(..., description="Module ciblé"),
    start: date = Query(..., description="Date de début"),
    end: date = Query(..., description="Date de fin"),
    bucket: str | None = Query(default=None, description="Granularité (day/week/month)"),
    include_dotation: bool = Query(default=True, description="Inclure les mouvements de dotation"),
    include_adjustment: bool = Query(
        default=True, description="Inclure les mouvements d'ajustement"
    ),
    user: models.User = Depends(get_current_user),
) -> models.ReportOverview:
    if not services.has_module_access(user, module, action="view"):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.get_reports_overview(
            module,
            start=start,
            end=end,
            bucket=bucket,
            include_dotation=include_dotation,
            include_adjustment=include_adjustment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export/csv")
async def export_csv(user: models.User = Depends(get_current_user)) -> FileResponse:
    _require_permission(user, action="view")
    with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        path = Path(tmp.name)
    services.export_items_to_csv(path)
    return FileResponse(path, filename="inventaire.csv", media_type="text/csv")

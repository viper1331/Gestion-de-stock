"""Routes pour l'export stock habillement."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from backend.api.auth import get_current_user
from backend.core import db, models, services
from backend.services.pdf_config import render_filename, resolve_pdf_config
from backend.services.pdf_inventory_exports import export_stock_inventory_pdf

router = APIRouter()

MODULE_KEY = "clothing"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/pdf/export")
async def export_stock_inventory_pdf_endpoint(
    q: str | None = Query(default=None, description="Filtre nom/SKU"),
    category: int | None = Query(default=None, description="Catégorie à filtrer"),
    below_threshold: bool = Query(default=False, description="Uniquement sous le seuil"),
    user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    _require_permission(user, action="view")
    site_key = db.get_current_site_key()
    filters = {
        "q": q,
        "category": category,
        "below_threshold": below_threshold,
    }
    try:
        resolved = resolve_pdf_config("inventory_habillement")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf_bytes = export_stock_inventory_pdf(site_key, user, filters)
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key=resolved.module_key,
        module_title=resolved.module_label,
    )
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)

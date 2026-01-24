"""Routes de génération de codes-barres."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from backend.api.auth import get_current_user
from backend.core import db, models, services
from backend.services import barcode as barcode_service
from backend.services.pdf_config import render_filename, resolve_pdf_config

router = APIRouter()

MODULE_KEY = "barcode"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.post("/generate/{sku}")
async def generate_barcode(
    sku: str, user: models.User = Depends(get_current_user)
) -> FileResponse:
    _require_permission(user, action="edit")
    site_key = db.get_current_site_key()
    path = barcode_service.generate_barcode_png(sku, site_key=site_key)
    if not path:
        raise HTTPException(status_code=500, detail="Échec de la génération du code-barres")
    return FileResponse(path, filename=f"{sku}.png", media_type="image/png")


@router.delete("/generate/{sku}")
async def delete_barcode(sku: str, user: models.User = Depends(get_current_user)) -> None:
    _require_permission(user, action="edit")
    site_key = db.get_current_site_key()
    barcode_service.delete_barcode_png(sku, site_key=site_key)


@router.get("", response_model=list[models.BarcodeGeneratedEntry])
async def list_barcodes(
    module: str | None = Query(default=None),
    q: str | None = Query(default=None),
    user: models.User = Depends(get_current_user),
) -> list[models.BarcodeGeneratedEntry]:
    _require_permission(user, action="view")
    try:
        return services.list_generated_barcodes(user, module=module, q=q)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# Assure la rétrocompatibilité avec l'URL historique terminée par un slash
router.add_api_route(
    "/",
    list_barcodes,
    methods=["GET"],
    include_in_schema=False,
)


@router.get("/existing", response_model=list[models.BarcodeValue])
async def list_existing_barcode_values(
    user: models.User = Depends(get_current_user),
) -> list[models.BarcodeValue]:
    _require_permission(user, action="view")
    return services.list_existing_barcodes(user)


@router.get("/catalog", response_model=list[models.BarcodeCatalogEntry])
async def list_barcode_catalog(
    module: str = Query("all"),
    q: str | None = Query(default=None),
    exclude_generated: bool = Query(default=False),
    user: models.User = Depends(get_current_user),
) -> list[models.BarcodeCatalogEntry]:
    _require_permission(user, action="view")
    return services.list_barcode_catalog(
        user, module=module, q=q, exclude_generated=exclude_generated
    )


@router.get("/assets/{filename}")
async def get_barcode_asset(
    filename: str, user: models.User = Depends(get_current_user)
) -> FileResponse:
    _require_permission(user, action="view")
    site_key = db.get_current_site_key()
    path = barcode_service.get_barcode_asset(filename, site_key=site_key)
    if not path:
        raise HTTPException(status_code=404, detail="Fichier de code-barres introuvable")
    return FileResponse(path, filename=path.name, media_type="image/png")


@router.get("/export/pdf")
async def export_barcode_pdf(user: models.User = Depends(get_current_user)) -> StreamingResponse:
    _require_permission(user, action="view")
    assets = services.list_accessible_barcode_assets(user)
    site_key = db.get_current_site_key()
    try:
        resolved = resolve_pdf_config(MODULE_KEY)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf_buffer = barcode_service.generate_barcode_pdf(
        assets=assets, config=resolved.config, site_key=site_key
    )
    if not pdf_buffer:
        raise HTTPException(status_code=404, detail="Aucun code-barres disponible pour l'export")
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key=MODULE_KEY,
        module_title=resolved.module_label,
    )
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)

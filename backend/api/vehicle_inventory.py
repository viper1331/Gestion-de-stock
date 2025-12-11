"""Routes pour la gestion de l'inventaire véhicules."""
from __future__ import annotations

import html
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from backend.api.auth import get_current_user
from backend.core import models, services
from backend.core.config import settings
from backend.services.pdf import VehiclePdfOptions
from backend.services import qrcode_service
from backend.services.debug_service import load_debug_config

logger = logging.getLogger("inventory_debug")

router = APIRouter()

QR_MODULE_KEY = "vehicle_qrcodes"
FALLBACK_MODULE_KEY = "vehicle_inventory"


def _is_inventory_debug_enabled() -> bool:
    try:
        return bool(load_debug_config().get("inventory_debug")) or settings.INVENTORY_DEBUG
    except Exception:
        return settings.INVENTORY_DEBUG


def _require_permission(user: models.User, *, action: str) -> None:
    if services.has_module_access(user, QR_MODULE_KEY, action=action):
        return
    if services.has_module_access(user, FALLBACK_MODULE_KEY, action=action):
        return
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.Item])
async def list_vehicle_items(
    search: str | None = Query(default=None, description="Filtre nom/SKU"),
    user: models.User = Depends(get_current_user),
) -> list[models.Item]:
    _require_permission(user, action="view")
    return services.list_vehicle_items(search)


class VehicleInventoryExportOptions(VehiclePdfOptions):
    pointer_targets: dict[str, models.PointerTarget] | None = None


def _vehicle_inventory_pdf_response(
    *, pointer_targets: dict[str, models.PointerTarget] | None, options: VehiclePdfOptions, user: models.User
):
    _require_permission(user, action="view")
    try:
        pdf_bytes = services.generate_vehicle_inventory_pdf(
            pointer_targets=pointer_targets,
            options=options,
        )
    except FileNotFoundError:
        fallback_options = options.model_copy()
        fallback_options.table_fallback = True
        pdf_bytes = services.generate_vehicle_inventory_pdf(
            pointer_targets=pointer_targets,
            options=fallback_options,
        )
    filename = f"inventaire_vehicules_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"",
        },
    )


@router.post("/export/pdf")
async def export_vehicle_inventory_pdf(
    payload: VehicleInventoryExportOptions | None = None,
    user: models.User = Depends(get_current_user),
):
    pointer_targets = payload.pointer_targets if payload else None
    options = payload or VehiclePdfOptions()
    return _vehicle_inventory_pdf_response(pointer_targets=pointer_targets, options=options, user=user)


@router.get("/export/pdf")
async def export_vehicle_inventory_pdf_legacy(
    user: models.User = Depends(get_current_user),
):
    return _vehicle_inventory_pdf_response(pointer_targets=None, options=VehiclePdfOptions(), user=user)


@router.get("/{item_id}/qr-code")
async def generate_vehicle_item_qr_code(
    item_id: int,
    request: Request,
    regenerate: bool = Query(
        default=False,
        description="Générer un nouveau lien sécurisé avant de créer le QR code",
    ),
    user: models.User = Depends(get_current_user),
):
    _require_permission(user, action="view")
    try:
        qr_token = services.get_vehicle_item_qr_token(item_id, regenerate=regenerate)
    except ValueError as exc:
        detail = str(exc)
        status_code = 400 if "affecté" in detail.lower() else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc

    item = services.get_vehicle_item(item_id)
    qr_target_url = item.shared_file_url or str(
        request.url_for("vehicle_item_public_page", qr_token=qr_token)
    )
    qr_buffer = qrcode_service.generate_qr_png(qr_target_url, label=f"Véhicule #{item_id}")
    headers = {
        "Content-Disposition": f"attachment; filename=vehicule-{item_id}-qr.png",
        "X-Vehicle-QR-Token": qr_token,
    }
    return StreamingResponse(qr_buffer, media_type="image/png", headers=headers)


@router.post("/", response_model=models.Item, status_code=201)
async def create_vehicle_item(
    payload: models.ItemCreate,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    inventory_debug_enabled = _is_inventory_debug_enabled()
    if inventory_debug_enabled:
        logger.debug("[INVENTORY_DEBUG] Incoming vehicle assignment: %s", payload.model_dump())
    try:
        vehicle = (
            services.get_vehicle_category(payload.category_id)
            if payload.category_id is not None
            else None
        )
        if (
            inventory_debug_enabled
            and vehicle
            and payload.size
            and payload.size not in (vehicle.sizes or [])
        ):
            logger.warning(
                "[INVENTORY_DEBUG] Invalid size received (fallback applied)",
                {"received": payload.size, "valid_views": vehicle.sizes},
            )
        new_item = services.create_vehicle_item(payload)
        if inventory_debug_enabled:
            logger.debug(
                "[INVENTORY_DEBUG] Saved vehicle item: %s",
                {
                    "item_id": new_item.id,
                    "size_saved": new_item.size,
                    "vehicle_views": vehicle.sizes if vehicle else None,
                },
            )
        return new_item
    except ValueError as exc:
        logger.error("[INVENTORY_DEBUG] Vehicle assignment failed", exc_info=True)
        detail = str(exc)
        status_code = 400
        if "introuvable" in detail.lower():
            status_code = 404
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception:
        logger.error("[INVENTORY_DEBUG] Vehicle assignment failed", exc_info=True)
        raise


@router.put("/{item_id}", response_model=models.Item)
async def update_vehicle_item(
    item_id: int,
    payload: models.ItemUpdate,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    inventory_debug_enabled = _is_inventory_debug_enabled()
    if inventory_debug_enabled:
        logger.debug("[INVENTORY_DEBUG] Incoming vehicle assignment: %s", payload.model_dump())
    try:
        existing_item = services.get_vehicle_item(item_id)
        target_category_id = (
            payload.category_id
            if payload.category_id is not None
            else existing_item.category_id
        )
        target_view = payload.size if payload.size is not None else existing_item.size

        vehicle = (
            services.get_vehicle_category(target_category_id)
            if target_category_id is not None
            else None
        )
        if (
            inventory_debug_enabled
            and vehicle
            and target_view
            and target_view not in (vehicle.sizes or [])
        ):
            logger.warning(
                "[INVENTORY_DEBUG] Invalid size received (fallback applied)",
                {"received": target_view, "valid_views": vehicle.sizes},
            )

        new_item = services.update_vehicle_item(item_id, payload)
        if inventory_debug_enabled:
            logger.debug(
                "[INVENTORY_DEBUG] Saved vehicle item: %s",
                {
                    "item_id": new_item.id,
                    "size_saved": new_item.size,
                    "vehicle_views": vehicle.sizes if vehicle else None,
                },
            )
        return new_item
    except ValueError as exc:
        logger.error("[INVENTORY_DEBUG] Vehicle assignment failed", exc_info=True)
        detail = str(exc)
        status_code = 400
        if "introuvable" in detail.lower():
            status_code = 404
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception:
        logger.error("[INVENTORY_DEBUG] Vehicle assignment failed", exc_info=True)
        raise


@router.delete("/{item_id}", status_code=204)
async def delete_vehicle_item(
    item_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_vehicle_item(item_id)


@router.post("/{item_id}/image", response_model=models.Item)
async def upload_vehicle_item_image(
    item_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.attach_vehicle_item_image(item_id, file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        await file.close()


@router.delete("/{item_id}/image", response_model=models.Item)
async def remove_vehicle_item_image(
    item_id: int, user: models.User = Depends(get_current_user)
) -> models.Item:
    _require_permission(user, action="edit")
    try:
        return services.remove_vehicle_item_image(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{item_id}/movements", status_code=204)
async def record_vehicle_movement(
    item_id: int,
    payload: models.MovementCreate,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.record_vehicle_movement(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/lots/{lot_id}/unassign", status_code=204)
async def unassign_vehicle_lot(
    lot_id: int,
    payload: models.VehicleLotUnassign,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.unassign_vehicle_lot(lot_id, payload.category_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "aucun" in detail.lower() or "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/{item_id}/movements", response_model=list[models.Movement])
async def fetch_vehicle_movements(
    item_id: int, user: models.User = Depends(get_current_user)
) -> list[models.Movement]:
    _require_permission(user, action="view")
    return services.fetch_vehicle_movements(item_id)


@router.get("/categories/", response_model=list[models.Category])
async def list_vehicle_categories(
    user: models.User = Depends(get_current_user),
) -> list[models.Category]:
    _require_permission(user, action="view")
    return services.list_vehicle_categories()


@router.post("/categories/", response_model=models.Category, status_code=201)
async def create_vehicle_category(
    payload: models.CategoryCreate, user: models.User = Depends(get_current_user)
) -> models.Category:
    _require_permission(user, action="edit")
    return services.create_vehicle_category(payload)


@router.post("/categories/{category_id}/image", response_model=models.Category)
async def upload_vehicle_category_image(
    category_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.attach_vehicle_category_image(category_id, file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        await file.close()


@router.delete("/categories/{category_id}/image", response_model=models.Category)
async def remove_vehicle_category_image(
    category_id: int, user: models.User = Depends(get_current_user)
) -> models.Category:
    _require_permission(user, action="edit")
    try:
        return services.remove_vehicle_category_image(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/categories/{category_id}", response_model=models.Category)
async def update_vehicle_category(
    category_id: int,
    payload: models.CategoryUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    try:
        return services.update_vehicle_category(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/categories/{category_id}", status_code=204)
async def delete_vehicle_category(
    category_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_vehicle_category(category_id)


@router.put(
    "/categories/{category_id}/views/background",
    response_model=models.VehicleViewConfig,
)
async def update_vehicle_view_background_endpoint(
    category_id: int,
    payload: models.VehicleViewBackgroundUpdate,
    user: models.User = Depends(get_current_user),
) -> models.VehicleViewConfig:
    _require_permission(user, action="edit")
    try:
        return services.update_vehicle_view_background(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/photos/", response_model=list[models.VehiclePhoto])
async def list_vehicle_photos(user: models.User = Depends(get_current_user)) -> list[models.VehiclePhoto]:
    _require_permission(user, action="view")
    return services.list_vehicle_photos()


@router.post("/photos/", response_model=models.VehiclePhoto, status_code=201)
async def upload_vehicle_photo(
    file: UploadFile = File(...), user: models.User = Depends(get_current_user)
) -> models.VehiclePhoto:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.add_vehicle_photo(file.file, file.filename)
    finally:
        await file.close()


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_vehicle_photo(
    photo_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_vehicle_photo(photo_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/public/{qr_token}", response_model=models.VehicleQrInfo)
async def fetch_public_vehicle_item(qr_token: str) -> models.VehicleQrInfo:
    try:
        return services.get_vehicle_item_public_info(qr_token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/public/{qr_token}/page",
    response_class=HTMLResponse,
    name="vehicle_item_public_page",
)
async def render_public_vehicle_page(qr_token: str) -> HTMLResponse:
    try:
        info = services.get_vehicle_item_public_info(qr_token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    title = html.escape(info.name)
    documentation_link = (
        f'<a href="{html.escape(info.documentation_url)}" target="_blank" rel="noopener">Consulter la documentation</a>'
        if info.documentation_url
        else "Aucune documentation n'est disponible pour cet équipement."
    )
    tutorial_link = (
        f'<a href="{html.escape(info.tutorial_url)}" target="_blank" rel="noopener">Ouvrir le tutoriel</a>'
        if info.tutorial_url
        else "Aucun tutoriel n'est disponible pour cet équipement."
    )
    category = html.escape(info.category_name) if info.category_name else "Non associé"
    image_section = (
        f'<img src="{html.escape(info.image_url)}" alt="{title}" style="max-width: 280px; border-radius: 8px;" />'
        if info.image_url
        else ""
    )

    html_content = f"""
    <!DOCTYPE html>
    <html lang=\"fr\">
      <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
        <title>{title} | Informations véhicule</title>
        <style>
          body {{
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(120deg, #0f172a 0%, #1e293b 45%, #0f172a 100%);
            color: #e2e8f0;
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
          }}
          .card {{
            background: rgba(15, 23, 42, 0.88);
            border: 1px solid rgba(148, 163, 184, 0.2);
            box-shadow: 0 20px 45px rgba(0, 0, 0, 0.35);
            border-radius: 16px;
            padding: 24px;
            max-width: 720px;
            width: calc(100% - 32px);
          }}
          h1 {{
            margin: 0 0 4px;
            font-size: 24px;
          }}
          p {{
            margin: 6px 0;
            color: #cbd5e1;
          }}
          a {{
            color: #38bdf8;
            text-decoration: none;
            font-weight: 600;
          }}
          a:hover {{
            text-decoration: underline;
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-top: 18px;
          }}
          .pill {{
            display: inline-block;
            background: rgba(148, 163, 184, 0.15);
            color: #cbd5e1;
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }}
        </style>
      </head>
      <body>
        <main class=\"card\">
          <div style=\"display:flex; align-items:center; gap:18px;\">
            <div style=\"flex:1;\">
              <h1>{title}</h1>
              <p class=\"pill\">Catégorie : {category}</p>
              <p>Référence : <strong>{html.escape(info.sku)}</strong></p>
            </div>
            {image_section}
          </div>
          <div class=\"grid\">
            <div>
              <h2 style=\"margin: 0 0 8px;\">Documentation</h2>
              <p>{documentation_link}</p>
            </div>
            <div>
              <h2 style=\"margin: 0 0 8px;\">Tutoriel</h2>
              <p>{tutorial_link}</p>
            </div>
          </div>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html_content)

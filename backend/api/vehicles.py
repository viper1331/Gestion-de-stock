"""Routes for vehicle subview pinning."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

QR_MODULE_KEY = "vehicle_qr"
FALLBACK_MODULE_KEY = "vehicle_inventory"


def _require_vehicle_permission(user: models.User, *, action: str) -> None:
    if services.has_module_access(user, QR_MODULE_KEY, action=action):
        return
    if services.has_module_access(user, FALLBACK_MODULE_KEY, action=action):
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get(
    "/vehicles/{vehicle_id}/library",
    response_model=models.VehicleLibraryResponse,
)
async def get_vehicle_library(
    vehicle_id: int,
    view_name: str | None = Query(default=None, description="Vue ciblée"),
    q: str | None = Query(default=None, description="Recherche par nom ou SKU"),
    include_lots: bool = Query(default=False, description="Inclure les lots"),
    user: models.User = Depends(get_current_user),
) -> models.VehicleLibraryResponse:
    _require_vehicle_permission(user, action="view")
    try:
        return services.list_vehicle_library_bundle(
            vehicle_id=vehicle_id,
            search=q,
            include_lots=include_lots,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get(
    "/vehicles/{vehicle_id}/views/{view_id}/pinned-subviews",
    response_model=models.VehiclePinnedSubviews,
)
async def get_vehicle_view_pinned_subviews(
    vehicle_id: int,
    view_id: str,
    user: models.User = Depends(get_current_user),
) -> models.VehiclePinnedSubviews:
    _require_vehicle_permission(user, action="view")
    try:
        pinned = services.list_vehicle_view_pinned_subviews(vehicle_id, view_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return models.VehiclePinnedSubviews(
        vehicle_id=vehicle_id, view_id=services._normalize_view_name(view_id), pinned=pinned
    )


@router.post(
    "/vehicles/{vehicle_id}/views/{view_id}/pinned-subviews",
    response_model=models.VehiclePinnedSubviews,
)
async def add_vehicle_view_pinned_subview(
    vehicle_id: int,
    view_id: str,
    payload: models.VehiclePinnedSubviewCreate,
    user: models.User = Depends(get_current_user),
) -> models.VehiclePinnedSubviews:
    _require_vehicle_permission(user, action="edit")
    raw_id = payload.subview_id
    if isinstance(raw_id, int):
        subview_id = str(raw_id)
        numeric_input = True
    elif isinstance(raw_id, str) and raw_id.isdigit():
        subview_id = raw_id
        numeric_input = True
    else:
        subview_id = raw_id
        numeric_input = False
    try:
        pinned = services.add_vehicle_view_pinned_subview(vehicle_id, view_id, subview_id)
    except ValueError as exc:
        detail = str(exc)
        if "sous-vue introuvable" in detail.lower():
            raise HTTPException(status_code=400, detail="Identifiant sous-vue invalide") from exc
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return models.VehiclePinnedSubviews(
        vehicle_id=vehicle_id, view_id=services._normalize_view_name(view_id), pinned=pinned
    )


@router.delete(
    "/vehicles/{vehicle_id}/views/{view_id}/pinned-subviews/{subview_id}",
    response_model=models.VehiclePinnedSubviews,
)
async def remove_vehicle_view_pinned_subview(
    vehicle_id: int,
    view_id: str,
    subview_id: str,
    user: models.User = Depends(get_current_user),
) -> models.VehiclePinnedSubviews:
    _require_vehicle_permission(user, action="edit")
    try:
        pinned = services.delete_vehicle_view_pinned_subview(
            vehicle_id, view_id, subview_id
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return models.VehiclePinnedSubviews(
        vehicle_id=vehicle_id, view_id=services._normalize_view_name(view_id), pinned=pinned
    )


@router.get(
    "/vehicles/{vehicle_id}/views/{view_id}/subview-pins",
    response_model=models.VehicleSubviewPinList,
)
async def list_vehicle_view_subview_pins(
    vehicle_id: int,
    view_id: str,
    user: models.User = Depends(get_current_user),
) -> models.VehicleSubviewPinList:
    _require_vehicle_permission(user, action="view")
    try:
        pins = services.list_subview_pins(vehicle_id, view_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return models.VehicleSubviewPinList(
        vehicle_id=vehicle_id,
        view_id=services._normalize_view_name(view_id),
        pins=pins,
    )


@router.post(
    "/vehicles/{vehicle_id}/views/{view_id}/subview-pins",
    response_model=models.VehicleSubviewPin,
)
async def create_vehicle_view_subview_pin(
    vehicle_id: int,
    view_id: str,
    payload: models.VehicleSubviewPinCreate,
    user: models.User = Depends(get_current_user),
) -> models.VehicleSubviewPin:
    _require_vehicle_permission(user, action="edit")
    try:
        pin = services.create_subview_pin(
            vehicle_id,
            view_id,
            payload.subview_id,
            payload.x_pct,
            payload.y_pct,
            user.username,
        )
    except ValueError as exc:
        detail = str(exc)
        if "déjà épinglée" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return pin


@router.patch(
    "/vehicles/{vehicle_id}/views/{view_id}/subview-pins/{pin_id}",
    response_model=models.VehicleSubviewPin,
)
async def update_vehicle_view_subview_pin(
    vehicle_id: int,
    view_id: str,
    pin_id: int,
    payload: models.VehicleSubviewPinUpdate,
    user: models.User = Depends(get_current_user),
) -> models.VehicleSubviewPin:
    _require_vehicle_permission(user, action="edit")
    existing = services.get_subview_pin(pin_id)
    if (
        existing is None
        or existing.vehicle_id != vehicle_id
        or services._normalize_view_name(view_id) != existing.view_id
    ):
        raise HTTPException(status_code=404, detail="Épinglage introuvable")
    try:
        pin = services.update_subview_pin(
            pin_id, payload.x_pct, payload.y_pct, user.username
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return pin


@router.delete(
    "/vehicles/{vehicle_id}/views/{view_id}/subview-pins/{pin_id}",
    status_code=204,
)
async def delete_vehicle_view_subview_pin(
    vehicle_id: int,
    view_id: str,
    pin_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_vehicle_permission(user, action="edit")
    existing = services.get_subview_pin(pin_id)
    if (
        existing is None
        or existing.vehicle_id != vehicle_id
        or services._normalize_view_name(view_id) != existing.view_id
    ):
        raise HTTPException(status_code=404, detail="Épinglage introuvable")
    try:
        services.delete_subview_pin(pin_id, user.username)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get(
    "/vehicles/{vehicle_id}/general-inventory/photo",
    response_model=models.VehicleGeneralInventoryPhoto,
)
async def get_vehicle_general_inventory_photo(
    vehicle_id: int,
    user: models.User = Depends(get_current_user),
) -> models.VehicleGeneralInventoryPhoto:
    _require_vehicle_permission(user, action="view")
    try:
        return services.get_vehicle_general_inventory_photo(vehicle_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post(
    "/vehicles/{vehicle_id}/general-inventory/photo",
    response_model=models.VehicleGeneralInventoryPhoto,
)
async def upload_vehicle_general_inventory_photo(
    vehicle_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.VehicleGeneralInventoryPhoto:
    _require_vehicle_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.upload_vehicle_general_inventory_photo(vehicle_id, file.file, file.filename)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    finally:
        await file.close()


@router.delete(
    "/vehicles/{vehicle_id}/general-inventory/photo",
    response_model=models.VehicleGeneralInventoryPhoto,
)
async def delete_vehicle_general_inventory_photo(
    vehicle_id: int,
    user: models.User = Depends(get_current_user),
) -> models.VehicleGeneralInventoryPhoto:
    _require_vehicle_permission(user, action="edit")
    try:
        return services.delete_vehicle_general_inventory_photo(vehicle_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

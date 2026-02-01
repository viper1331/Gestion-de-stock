"""Routes for vehicle subview pinning."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

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
        if not numeric_input and "sous-vue introuvable" in detail.lower():
            raise HTTPException(
                status_code=400, detail="Identifiant sous-vue invalide"
            ) from exc
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

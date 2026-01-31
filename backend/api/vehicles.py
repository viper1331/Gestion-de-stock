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
    try:
        pinned = services.add_vehicle_view_pinned_subview(
            vehicle_id, view_id, payload.subview_id
        )
    except ValueError as exc:
        detail = str(exc)
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

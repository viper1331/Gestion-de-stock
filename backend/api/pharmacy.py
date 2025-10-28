"""Routes pour la gestion de la pharmacie."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "pharmacy"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.get("/", response_model=list[models.PharmacyItem])
async def list_pharmacy_items(
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyItem]:
    _require_permission(user, action="view")
    return services.list_pharmacy_items()


@router.post("/", response_model=models.PharmacyItem, status_code=201)
async def create_pharmacy_item(
    payload: models.PharmacyItemCreate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="edit")
    return services.create_pharmacy_item(payload)


@router.get("/{item_id}", response_model=models.PharmacyItem)
async def get_pharmacy_item(
    item_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="view")
    try:
        return services.get_pharmacy_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Pharmacy item not found") from exc


@router.put("/{item_id}", response_model=models.PharmacyItem)
async def update_pharmacy_item(
    item_id: int,
    payload: models.PharmacyItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_item(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Pharmacy item not found") from exc


@router.delete("/{item_id}", status_code=204)
async def delete_pharmacy_item(
    item_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_pharmacy_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Pharmacy item not found") from exc

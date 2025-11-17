"""Routes pour la gestion de l'inventaire remises."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "inventory_remise"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.Item])
async def list_remise_items(
    search: str | None = Query(default=None, description="Filtre nom/SKU"),
    user: models.User = Depends(get_current_user),
) -> list[models.Item]:
    _require_permission(user, action="view")
    return services.list_remise_items(search)


@router.post("/", response_model=models.Item, status_code=201)
async def create_remise_item(
    payload: models.ItemCreate, user: models.User = Depends(get_current_user)
) -> models.Item:
    _require_permission(user, action="edit")
    return services.create_remise_item(payload)


@router.put("/{item_id}", response_model=models.Item)
async def update_remise_item(
    item_id: int,
    payload: models.ItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    try:
        return services.update_remise_item(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{item_id}", status_code=204)
async def delete_remise_item(
    item_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_remise_item(item_id)


@router.post("/{item_id}/movements", status_code=204)
async def record_remise_movement(
    item_id: int,
    payload: models.MovementCreate,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.record_remise_movement(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{item_id}/movements", response_model=list[models.Movement])
async def fetch_remise_movements(
    item_id: int, user: models.User = Depends(get_current_user)
) -> list[models.Movement]:
    _require_permission(user, action="view")
    return services.fetch_remise_movements(item_id)


@router.get("/categories/", response_model=list[models.Category])
async def list_remise_categories(
    user: models.User = Depends(get_current_user),
) -> list[models.Category]:
    _require_permission(user, action="view")
    return services.list_remise_categories()


@router.post("/categories/", response_model=models.Category, status_code=201)
async def create_remise_category(
    payload: models.CategoryCreate, user: models.User = Depends(get_current_user)
) -> models.Category:
    _require_permission(user, action="edit")
    return services.create_remise_category(payload)


@router.put("/categories/{category_id}", response_model=models.Category)
async def update_remise_category(
    category_id: int,
    payload: models.CategoryUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    try:
        return services.update_remise_category(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/categories/{category_id}", status_code=204)
async def delete_remise_category(
    category_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_remise_category(category_id)


@router.get("/lots/", response_model=list[models.RemiseLot])
async def list_remise_lots(user: models.User = Depends(get_current_user)) -> list[models.RemiseLot]:
    _require_permission(user, action="view")
    return services.list_remise_lots()


@router.post("/lots/", response_model=models.RemiseLot, status_code=201)
async def create_remise_lot(
    payload: models.RemiseLotCreate, user: models.User = Depends(get_current_user)
) -> models.RemiseLot:
    _require_permission(user, action="edit")
    return services.create_remise_lot(payload)


@router.put("/lots/{lot_id}", response_model=models.RemiseLot)
async def update_remise_lot(
    lot_id: int,
    payload: models.RemiseLotUpdate,
    user: models.User = Depends(get_current_user),
) -> models.RemiseLot:
    _require_permission(user, action="edit")
    try:
        return services.update_remise_lot(lot_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/lots/{lot_id}", status_code=204)
async def delete_remise_lot(
    lot_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_remise_lot(lot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/lots/{lot_id}/items", response_model=list[models.RemiseLotItem])
async def list_remise_lot_items(
    lot_id: int, user: models.User = Depends(get_current_user)
) -> list[models.RemiseLotItem]:
    _require_permission(user, action="view")
    try:
        return services.list_remise_lot_items(lot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/lots/{lot_id}/items", response_model=models.RemiseLotItem, status_code=201
)
async def add_remise_lot_item(
    lot_id: int,
    payload: models.RemiseLotItemBase,
    user: models.User = Depends(get_current_user),
) -> models.RemiseLotItem:
    _require_permission(user, action="edit")
    try:
        return services.add_remise_lot_item(lot_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/lots/{lot_id}/items/{lot_item_id}", response_model=models.RemiseLotItem)
async def update_remise_lot_item(
    lot_id: int,
    lot_item_id: int,
    payload: models.RemiseLotItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.RemiseLotItem:
    _require_permission(user, action="edit")
    try:
        return services.update_remise_lot_item(lot_id, lot_item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/lots/{lot_id}/items/{lot_item_id}", status_code=204)
async def remove_remise_lot_item(
    lot_id: int, lot_item_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.remove_remise_lot_item(lot_id, lot_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

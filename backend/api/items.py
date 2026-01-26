"""Routes pour les articles et mouvements."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "clothing"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_permission_for_module(user: models.User, module_key: str, *, action: str) -> None:
    if not services.has_module_access(user, module_key, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _resolve_barcode_module(module: str) -> tuple[str, str]:
    normalized = module.strip().lower()
    if normalized == "clothing":
        return "clothing", "clothing"
    if normalized == "remise":
        return "inventory_remise", "remise"
    if normalized == "pharmacy":
        return "pharmacy", "pharmacy"
    raise ValueError("Module invalide")


@router.get("/by-barcode", response_model=models.BarcodeLookupItem)
async def find_item_by_barcode(
    module: str = Query(..., description="Module source (clothing, remise, pharmacy)"),
    barcode: str = Query(..., description="Code-barres scanné"),
    user: models.User = Depends(get_current_user),
) -> models.BarcodeLookupItem:
    try:
        module_key, service_module = _resolve_barcode_module(module)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _require_permission_for_module(user, module_key, action="view")
    try:
        matches = services.find_items_by_barcode(service_module, barcode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not matches:
        raise HTTPException(status_code=404, detail="Code-barres introuvable")
    if len(matches) > 1:
        return JSONResponse(
            status_code=409,
            content={"matches": [match.model_dump() for match in matches]},
        )
    return matches[0]


@router.get("/", response_model=list[models.Item])
async def list_items(
    search: str | None = Query(default=None, description="Filtre nom/SKU"),
    user: models.User = Depends(get_current_user),
) -> list[models.Item]:
    _require_permission(user, action="view")
    return services.list_items(search)


@router.get("/stats", response_model=models.InventoryStats)
async def get_clothing_stats(
    user: models.User = Depends(get_current_user),
) -> models.InventoryStats:
    _require_permission(user, action="view")
    return services.get_inventory_stats("clothing")


@router.post("/", response_model=models.Item, status_code=201)
async def create_item(payload: models.ItemCreate, user: models.User = Depends(get_current_user)) -> models.Item:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.create_item(payload)


@router.put("/{item_id}", response_model=models.Item)
async def update_item(item_id: int, payload: models.ItemUpdate, user: models.User = Depends(get_current_user)) -> models.Item:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.update_item(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: int, user: models.User = Depends(get_current_user)) -> None:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    services.delete_item(item_id)


@router.post("/{item_id}/movements", status_code=204)
async def record_movement(item_id: int, payload: models.MovementCreate, user: models.User = Depends(get_current_user)) -> None:
    _require_permission(user, action="edit")
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        services.record_movement(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{item_id}/movements", response_model=list[models.Movement])
async def fetch_movements(item_id: int, user: models.User = Depends(get_current_user)) -> list[models.Movement]:
    _require_permission(user, action="view")
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.fetch_movements(item_id)

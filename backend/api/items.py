"""Routes pour les articles et mouvements."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/", response_model=list[models.Item])
async def list_items(search: str | None = Query(default=None, description="Filtre nom/SKU")) -> list[models.Item]:
    return services.list_items(search)


@router.post("/", response_model=models.Item, status_code=201)
async def create_item(payload: models.ItemCreate, user: models.User = Depends(get_current_user)) -> models.Item:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.create_item(payload)


@router.put("/{item_id}", response_model=models.Item)
async def update_item(item_id: int, payload: models.ItemUpdate, user: models.User = Depends(get_current_user)) -> models.Item:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.update_item(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: int, user: models.User = Depends(get_current_user)) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    services.delete_item(item_id)


@router.post("/{item_id}/movements", status_code=204)
async def record_movement(item_id: int, payload: models.MovementCreate, user: models.User = Depends(get_current_user)) -> None:
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        services.record_movement(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{item_id}/movements", response_model=list[models.Movement])
async def fetch_movements(item_id: int, user: models.User = Depends(get_current_user)) -> list[models.Movement]:
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.fetch_movements(item_id)

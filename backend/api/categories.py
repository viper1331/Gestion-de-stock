"""Routes pour la gestion des catégories."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "clothing"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.Category])
async def list_categories(user: models.User = Depends(get_current_user)) -> list[models.Category]:
    _require_permission(user, action="view")
    return services.list_categories()


@router.post("/", response_model=models.Category, status_code=201)
async def create_category(payload: models.CategoryCreate, user: models.User = Depends(get_current_user)) -> models.Category:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.create_category(payload)


@router.put("/{category_id}", response_model=models.Category)
async def update_category(
    category_id: int,
    payload: models.CategoryUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.update_category(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: int, user: models.User = Depends(get_current_user)) -> None:
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    services.delete_category(category_id)

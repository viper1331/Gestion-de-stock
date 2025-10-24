"""Routes pour la gestion des catégories."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/", response_model=list[models.Category])
async def list_categories() -> list[models.Category]:
    return services.list_categories()


@router.post("/", response_model=models.Category, status_code=201)
async def create_category(payload: models.CategoryCreate, user: models.User = Depends(get_current_user)) -> models.Category:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return services.create_category(payload)


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: int, user: models.User = Depends(get_current_user)) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    services.delete_category(category_id)

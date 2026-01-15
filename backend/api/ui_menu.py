"""Routes pour la personnalisation du menu UI."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/menu-order", response_model=models.MenuOrderResponse)
def get_menu_order(
    menu_key: str = "main_modules",
    current_user: models.User = Depends(get_current_user),
) -> models.MenuOrderResponse:
    normalized_key = menu_key.strip() if menu_key else "main_modules"
    order = services.get_menu_order(current_user.username, normalized_key) or []
    return models.MenuOrderResponse(menu_key=normalized_key, order=order)


@router.put("/menu-order", response_model=models.MenuOrderResponse)
def set_menu_order(
    payload: models.MenuOrderPayload,
    current_user: models.User = Depends(get_current_user),
) -> models.MenuOrderResponse:
    order = services.set_menu_order(current_user.username, payload.menu_key, payload.order)
    return models.MenuOrderResponse(menu_key=payload.menu_key, order=order)

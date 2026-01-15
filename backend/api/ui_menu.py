"""Routes pour la personnalisation du menu UI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()


@router.get("/menu-order", response_model=models.MenuOrderResponse | None)
def get_menu_order(
    menu_key: str = "main_menu",
    current_user: models.User = Depends(get_current_user),
) -> models.MenuOrderResponse | None:
    normalized_key = menu_key.strip() if menu_key else "main_menu"
    if not normalized_key:
        raise HTTPException(status_code=400, detail="menu_key invalide")
    site_key = db.get_current_site_key()
    order = services.get_menu_order(current_user.username, site_key, normalized_key)
    if not order:
        return None
    return models.MenuOrderResponse(
        menu_key=normalized_key,
        version=order["version"],
        items=order["items"],
    )


@router.put("/menu-order", response_model=models.MenuOrderResponse)
def set_menu_order(
    payload: models.MenuOrderPayload,
    menu_key: str = "main_menu",
    current_user: models.User = Depends(get_current_user),
) -> models.MenuOrderResponse:
    normalized_key = menu_key.strip() if menu_key else "main_menu"
    if not normalized_key:
        raise HTTPException(status_code=400, detail="menu_key invalide")
    site_key = db.get_current_site_key()
    try:
        stored = services.set_menu_order(
            current_user.username, site_key, normalized_key, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return models.MenuOrderResponse(
        menu_key=normalized_key,
        version=stored["version"],
        items=stored["items"],
    )

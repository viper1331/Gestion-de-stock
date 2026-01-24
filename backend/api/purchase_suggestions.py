"""Routes pour les suggestions de bons de commande."""
from __future__ import annotations

from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()

_SUGGESTION_MODULES: set[str] = {"clothing", "pharmacy", "inventory_remise"}
MODULE_KEY = "purchase_suggestions"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _allowed_modules(user: models.User, *, action: str) -> list[str]:
    if user.role == "admin":
        return sorted(_SUGGESTION_MODULES)
    entries = services.list_module_permissions_for_user(user.id)
    allowed: list[str] = []
    for entry in entries:
        if entry.module not in _SUGGESTION_MODULES:
            continue
        if action == "edit" and not entry.can_edit:
            continue
        if action == "view" and not entry.can_view:
            continue
        allowed.append(entry.module)
    return sorted(set(allowed))


def _validate_modules(modules: Iterable[str], allowed: list[str]) -> list[str]:
    normalized: list[str] = []
    for module in modules:
        module_key = (module or "").strip()
        if not module_key:
            continue
        if module_key not in _SUGGESTION_MODULES:
            raise HTTPException(status_code=400, detail=f"Module inconnu: {module_key}")
        if module_key not in allowed:
            raise HTTPException(status_code=403, detail="Accès refusé au module demandé.")
        normalized.append(module_key)
    return sorted(set(normalized))


@router.get("/purchasing/suggestions")
async def list_suggestions(
    status: str | None = None,
    module: str | None = None,
    user: models.User = Depends(get_current_user),
) -> list[models.PurchaseSuggestionDetail]:
    _require_permission(user, action="view")
    allowed = _allowed_modules(user, action="view")
    if module:
        requested = _validate_modules([module], allowed)
        module_key = requested[0] if requested else None
    else:
        module_key = None
    site_key = db.get_current_site_key()
    return services.list_purchase_suggestions(
        site_key=site_key,
        status=status,
        module_key=module_key,
        allowed_modules=allowed,
    )


@router.post("/purchasing/suggestions/refresh")
async def refresh_suggestions(
    payload: models.PurchaseSuggestionRefreshPayload,
    user: models.User = Depends(get_current_user),
) -> list[models.PurchaseSuggestionDetail]:
    _require_permission(user, action="edit")
    allowed = _allowed_modules(user, action="edit")
    if not allowed:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    requested = payload.module_keys or allowed
    modules = _validate_modules(requested, allowed)
    site_key = db.get_current_site_key()
    return services.refresh_purchase_suggestions(
        site_key=site_key,
        module_keys=modules,
        created_by=user.username,
    )


@router.patch("/purchasing/suggestions/{suggestion_id}")
async def update_suggestion(
    suggestion_id: int,
    payload: models.PurchaseSuggestionUpdatePayload,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseSuggestionDetail:
    _require_permission(user, action="edit")
    suggestion = services.get_purchase_suggestion(suggestion_id)
    allowed = _allowed_modules(user, action="edit")
    if suggestion.module_key not in allowed:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    try:
        return services.update_purchase_suggestion_lines(suggestion_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/purchasing/suggestions/{suggestion_id}/convert")
async def convert_suggestion(
    suggestion_id: int, user: models.User = Depends(get_current_user)
) -> models.PurchaseSuggestionConvertResult:
    _require_permission(user, action="edit")
    suggestion = services.get_purchase_suggestion(suggestion_id)
    allowed = _allowed_modules(user, action="edit")
    if suggestion.module_key not in allowed:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    try:
        return services.convert_purchase_suggestion_to_po(suggestion_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

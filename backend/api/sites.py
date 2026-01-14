"""Routes de sélection des bases de données par site."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.auth import get_current_user
from backend.core import models, sites

router = APIRouter()


@router.get("/active", response_model=models.SiteContext)
async def get_active_site(
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models.SiteContext:
    site_list = sites.list_sites() if user.role == "admin" else None
    return sites.resolve_site_context(user, request.headers.get("X-Site-Key"), site_list)


@router.put("/active", response_model=models.SiteContext)
async def update_active_site(
    payload: models.SiteSelectionRequest,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models.SiteContext:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        normalized = sites.normalize_site_key(payload.site_key) if payload.site_key else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sites.set_user_site_override(user.username, normalized)
    site_list = sites.list_sites()
    return sites.resolve_site_context(user, request.headers.get("X-Site-Key"), site_list)

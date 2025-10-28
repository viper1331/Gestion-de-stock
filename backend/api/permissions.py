"""Routes pour la gestion granulaire des droits modules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/modules", response_model=list[models.ModulePermission])
async def list_module_permissions(
    user: models.User = Depends(get_current_user),
) -> list[models.ModulePermission]:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return services.list_module_permissions()


@router.get("/modules/me", response_model=list[models.ModulePermission])
async def list_my_module_permissions(
    user: models.User = Depends(get_current_user),
) -> list[models.ModulePermission]:
    return services.list_module_permissions_for_role(user.role)


@router.get("/modules/{role}/{module}", response_model=models.ModulePermission)
async def get_module_permission(
    role: str,
    module: str,
    user: models.User = Depends(get_current_user),
) -> models.ModulePermission:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    permission = services.get_module_permission(role, module)
    if permission is None:
        raise HTTPException(status_code=404, detail="Module permission not found")
    return permission


@router.put("/modules", response_model=models.ModulePermission)
async def upsert_module_permission(
    payload: models.ModulePermissionUpsert,
    user: models.User = Depends(get_current_user),
) -> models.ModulePermission:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return services.upsert_module_permission(payload)


@router.delete("/modules/{role}/{module}", status_code=204)
async def delete_module_permission(
    role: str,
    module: str,
    user: models.User = Depends(get_current_user),
) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        services.delete_module_permission(role, module)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Module permission not found") from exc

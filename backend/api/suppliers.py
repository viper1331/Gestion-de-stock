"""Routes pour la gestion des fournisseurs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "suppliers"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user.role, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.get("/", response_model=list[models.Supplier])
async def list_suppliers(user: models.User = Depends(get_current_user)) -> list[models.Supplier]:
    _require_permission(user, action="view")
    return services.list_suppliers()


@router.post("/", response_model=models.Supplier, status_code=201)
async def create_supplier(
    payload: models.SupplierCreate, user: models.User = Depends(get_current_user)
) -> models.Supplier:
    _require_permission(user, action="edit")
    return services.create_supplier(payload)


@router.get("/{supplier_id}", response_model=models.Supplier)
async def get_supplier(
    supplier_id: int, user: models.User = Depends(get_current_user)
) -> models.Supplier:
    _require_permission(user, action="view")
    try:
        return services.get_supplier(supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Supplier not found") from exc


@router.put("/{supplier_id}", response_model=models.Supplier)
async def update_supplier(
    supplier_id: int,
    payload: models.SupplierUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Supplier:
    _require_permission(user, action="edit")
    try:
        return services.update_supplier(supplier_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Supplier not found") from exc


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(
    supplier_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_supplier(supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Supplier not found") from exc

"""Routes pour la gestion des fournisseurs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()

MODULE_KEY = "suppliers"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.Supplier])
async def list_suppliers(
    module: str | None = Query(default=None),
    user: models.User = Depends(get_current_user),
) -> list[models.Supplier]:
    if not services.has_module_access(user, MODULE_KEY, action="view"):
        return []
    site_key = db.get_current_site_key()
    return services.list_suppliers(site_key=site_key, module=module)


@router.post("/", response_model=models.Supplier, status_code=201)
async def create_supplier(
    payload: models.SupplierCreate, user: models.User = Depends(get_current_user)
) -> models.Supplier:
    _require_permission(user, action="edit")
    site_key = db.get_current_site_key()
    return services.create_supplier(site_key, payload)


@router.get("/{supplier_id}", response_model=models.Supplier)
async def get_supplier(
    supplier_id: int, user: models.User = Depends(get_current_user)
) -> models.Supplier:
    _require_permission(user, action="view")
    try:
        site_key = db.get_current_site_key()
        return services.get_supplier(site_key, supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{supplier_id}", response_model=models.Supplier)
async def update_supplier(
    supplier_id: int,
    payload: models.SupplierUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Supplier:
    _require_permission(user, action="edit")
    try:
        site_key = db.get_current_site_key()
        return services.update_supplier(site_key, supplier_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(
    supplier_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        site_key = db.get_current_site_key()
        services.delete_supplier(site_key, supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

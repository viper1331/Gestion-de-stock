from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.admin import require_admin
from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


def _resolve_module_access(module: models.LinkCategoryModule) -> str:
    if module == "vehicle_qr":
        return "vehicle_qrcodes"
    return "pharmacy"


@router.get("/", response_model=list[models.LinkCategory])
def list_link_categories(
    module: models.LinkCategoryModule = Query(..., description="Module ciblé"),
    user: models.User = Depends(get_current_user),
) -> list[models.LinkCategory]:
    include_inactive = user.role == "admin"
    if user.role != "admin":
        module_key = _resolve_module_access(module)
        if not services.has_module_access(user, module_key, action="view"):
            raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.list_link_categories(module, include_inactive=include_inactive)


@router.post("/", response_model=models.LinkCategory, status_code=201)
def create_link_category(
    payload: models.LinkCategoryCreate, _: object = Depends(require_admin)
) -> models.LinkCategory:
    try:
        return services.create_link_category(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{category_id}", response_model=models.LinkCategory)
def update_link_category(
    category_id: int,
    payload: models.LinkCategoryUpdate,
    _: object = Depends(require_admin),
) -> models.LinkCategory:
    try:
        return services.update_link_category(category_id, payload)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.delete("/{category_id}", status_code=204)
def delete_link_category(
    category_id: int, _: object = Depends(require_admin)
) -> None:
    try:
        services.delete_link_category(category_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404, detail=detail) from exc

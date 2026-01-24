from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

QR_MODULE_KEY = "vehicle_qr"
PHARMACY_LINKS_MODULE_KEY = "pharmacy_links"


def _require_vehicle_qr_access(user: models.User, *, action: str) -> None:
    if services.has_module_access(user, QR_MODULE_KEY, action=action):
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_pharmacy_access(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, PHARMACY_LINKS_MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _raise_link_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status = 404 if "introuvable" in detail.lower() else 400
    return HTTPException(status_code=status, detail=detail)


@router.get(
    "/vehicle-qr/items/{item_id}/links",
    response_model=list[models.LinkCategoryValue],
)
def list_vehicle_item_links(
    item_id: int, user: models.User = Depends(get_current_user)
) -> list[models.LinkCategoryValue]:
    _require_vehicle_qr_access(user, action="view")
    try:
        return services.get_item_links("vehicle_qr", item_id)
    except ValueError as exc:
        raise _raise_link_error(exc) from exc


@router.put(
    "/vehicle-qr/items/{item_id}/links",
    response_model=list[models.LinkCategoryValue],
)
def save_vehicle_item_links(
    item_id: int,
    payload: models.LinkItemUpdate,
    user: models.User = Depends(get_current_user),
) -> list[models.LinkCategoryValue]:
    _require_vehicle_qr_access(user, action="edit")
    try:
        return services.save_item_links("vehicle_qr", item_id, payload.links)
    except ValueError as exc:
        raise _raise_link_error(exc) from exc


@router.get(
    "/pharmacy/items/{item_id}/links",
    response_model=list[models.LinkCategoryValue],
)
def list_pharmacy_item_links(
    item_id: int, user: models.User = Depends(get_current_user)
) -> list[models.LinkCategoryValue]:
    _require_pharmacy_access(user, action="view")
    try:
        return services.get_item_links("pharmacy", item_id)
    except ValueError as exc:
        raise _raise_link_error(exc) from exc


@router.put(
    "/pharmacy/items/{item_id}/links",
    response_model=list[models.LinkCategoryValue],
)
def save_pharmacy_item_links(
    item_id: int,
    payload: models.LinkItemUpdate,
    user: models.User = Depends(get_current_user),
) -> list[models.LinkCategoryValue]:
    _require_pharmacy_access(user, action="edit")
    try:
        return services.save_item_links("pharmacy", item_id, payload.links)
    except ValueError as exc:
        raise _raise_link_error(exc) from exc

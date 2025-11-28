"""Routes pour la gestion de la pharmacie."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "pharmacy"


def _pharmacy_http_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if "introuvable" in detail.lower():
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.PharmacyItem])
async def list_pharmacy_items(
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyItem]:
    _require_permission(user, action="view")
    return services.list_pharmacy_items()


@router.post("/", response_model=models.PharmacyItem, status_code=201)
async def create_pharmacy_item(
    payload: models.PharmacyItemCreate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="edit")
    try:
        return services.create_pharmacy_item(payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.get("/categories/", response_model=list[models.PharmacyCategory])
async def list_pharmacy_categories(
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyCategory]:
    _require_permission(user, action="view")
    return services.list_pharmacy_categories()


@router.post("/categories/", response_model=models.PharmacyCategory, status_code=201)
async def create_pharmacy_category(
    payload: models.PharmacyCategoryCreate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyCategory:
    _require_permission(user, action="edit")
    return services.create_pharmacy_category(payload)


@router.put("/categories/{category_id}", response_model=models.PharmacyCategory)
async def update_pharmacy_category(
    category_id: int,
    payload: models.PharmacyCategoryUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyCategory:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_category(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/categories/{category_id}", status_code=204)
async def delete_pharmacy_category(
    category_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    services.delete_pharmacy_category(category_id)


@router.get("/{item_id}", response_model=models.PharmacyItem)
async def get_pharmacy_item(
    item_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="view")
    try:
        return services.get_pharmacy_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{item_id}", response_model=models.PharmacyItem)
async def update_pharmacy_item(
    item_id: int,
    payload: models.PharmacyItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyItem:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_item(item_id, payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.delete("/{item_id}", status_code=204)
async def delete_pharmacy_item(
    item_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_pharmacy_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{item_id}/movements", status_code=204)
async def record_pharmacy_movement(
    item_id: int,
    payload: models.PharmacyMovementCreate,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.record_pharmacy_movement(item_id, payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.get(
    "/{item_id}/movements",
    response_model=list[models.PharmacyMovement],
)
async def fetch_pharmacy_movements(
    item_id: int,
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyMovement]:
    _require_permission(user, action="view")
    return services.fetch_pharmacy_movements(item_id)


@router.get("/lots/", response_model=list[models.PharmacyLot])
async def list_pharmacy_lots(user: models.User = Depends(get_current_user)) -> list[models.PharmacyLot]:
    _require_permission(user, action="view")
    return services.list_pharmacy_lots()


@router.get("/lots/with-items", response_model=list[models.PharmacyLotWithItems])
async def list_pharmacy_lots_with_items(
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyLotWithItems]:
    _require_permission(user, action="view")
    return services.list_pharmacy_lots_with_items()


@router.post("/lots/", response_model=models.PharmacyLot, status_code=201)
async def create_pharmacy_lot(
    payload: models.PharmacyLotCreate, user: models.User = Depends(get_current_user)
) -> models.PharmacyLot:
    _require_permission(user, action="edit")
    return services.create_pharmacy_lot(payload)


@router.put("/lots/{lot_id}", response_model=models.PharmacyLot)
async def update_pharmacy_lot(
    lot_id: int,
    payload: models.PharmacyLotUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyLot:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_lot(lot_id, payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.post("/lots/{lot_id}/image", response_model=models.PharmacyLot)
async def upload_pharmacy_lot_image(
    lot_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.PharmacyLot:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.attach_pharmacy_lot_image(lot_id, file.file, file.filename)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc
    finally:
        await file.close()


@router.delete("/lots/{lot_id}/image", response_model=models.PharmacyLot)
async def remove_pharmacy_lot_image(
    lot_id: int, user: models.User = Depends(get_current_user)
) -> models.PharmacyLot:
    _require_permission(user, action="edit")
    try:
        return services.remove_pharmacy_lot_image(lot_id)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.delete("/lots/{lot_id}", status_code=204)
async def delete_pharmacy_lot(
    lot_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_pharmacy_lot(lot_id)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.get("/lots/{lot_id}/items", response_model=list[models.PharmacyLotItem])
async def list_pharmacy_lot_items(
    lot_id: int, user: models.User = Depends(get_current_user)
) -> list[models.PharmacyLotItem]:
    _require_permission(user, action="view")
    try:
        return services.list_pharmacy_lot_items(lot_id)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.post(
    "/lots/{lot_id}/items", response_model=models.PharmacyLotItem, status_code=201
)
async def add_pharmacy_lot_item(
    lot_id: int,
    payload: models.PharmacyLotItemBase,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyLotItem:
    _require_permission(user, action="edit")
    try:
        return services.add_pharmacy_lot_item(lot_id, payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.put("/lots/{lot_id}/items/{lot_item_id}", response_model=models.PharmacyLotItem)
async def update_pharmacy_lot_item(
    lot_id: int,
    lot_item_id: int,
    payload: models.PharmacyLotItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyLotItem:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_lot_item(lot_id, lot_item_id, payload)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc


@router.delete("/lots/{lot_id}/items/{lot_item_id}", status_code=204)
async def remove_pharmacy_lot_item(
    lot_id: int, lot_item_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.remove_pharmacy_lot_item(lot_id, lot_item_id)
    except ValueError as exc:
        raise _pharmacy_http_error(exc) from exc



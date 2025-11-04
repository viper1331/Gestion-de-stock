"""Routes pour la gestion de l'inventaire véhicules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "vehicle_inventory"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.Item])
async def list_vehicle_items(
    search: str | None = Query(default=None, description="Filtre nom/SKU"),
    user: models.User = Depends(get_current_user),
) -> list[models.Item]:
    _require_permission(user, action="view")
    return services.list_vehicle_items(search)


@router.post("/", response_model=models.Item, status_code=201)
async def create_vehicle_item(
    payload: models.ItemCreate, user: models.User = Depends(get_current_user)
) -> models.Item:
    _require_permission(user, action="edit")
    return services.create_vehicle_item(payload)


@router.put("/{item_id}", response_model=models.Item)
async def update_vehicle_item(
    item_id: int,
    payload: models.ItemUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    try:
        return services.update_vehicle_item(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{item_id}", status_code=204)
async def delete_vehicle_item(
    item_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_vehicle_item(item_id)


@router.post("/{item_id}/image", response_model=models.Item)
async def upload_vehicle_item_image(
    item_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.Item:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.attach_vehicle_item_image(item_id, file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        await file.close()


@router.delete("/{item_id}/image", response_model=models.Item)
async def remove_vehicle_item_image(
    item_id: int, user: models.User = Depends(get_current_user)
) -> models.Item:
    _require_permission(user, action="edit")
    try:
        return services.remove_vehicle_item_image(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{item_id}/movements", status_code=204)
async def record_vehicle_movement(
    item_id: int,
    payload: models.MovementCreate,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.record_vehicle_movement(item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{item_id}/movements", response_model=list[models.Movement])
async def fetch_vehicle_movements(
    item_id: int, user: models.User = Depends(get_current_user)
) -> list[models.Movement]:
    _require_permission(user, action="view")
    return services.fetch_vehicle_movements(item_id)


@router.get("/categories/", response_model=list[models.Category])
async def list_vehicle_categories(
    user: models.User = Depends(get_current_user),
) -> list[models.Category]:
    _require_permission(user, action="view")
    return services.list_vehicle_categories()


@router.post("/categories/", response_model=models.Category, status_code=201)
async def create_vehicle_category(
    payload: models.CategoryCreate, user: models.User = Depends(get_current_user)
) -> models.Category:
    _require_permission(user, action="edit")
    return services.create_vehicle_category(payload)


@router.post("/categories/{category_id}/image", response_model=models.Category)
async def upload_vehicle_category_image(
    category_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.attach_vehicle_category_image(category_id, file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        await file.close()


@router.delete("/categories/{category_id}/image", response_model=models.Category)
async def remove_vehicle_category_image(
    category_id: int, user: models.User = Depends(get_current_user)
) -> models.Category:
    _require_permission(user, action="edit")
    try:
        return services.remove_vehicle_category_image(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/categories/{category_id}", response_model=models.Category)
async def update_vehicle_category(
    category_id: int,
    payload: models.CategoryUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Category:
    _require_permission(user, action="edit")
    try:
        return services.update_vehicle_category(category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/categories/{category_id}", status_code=204)
async def delete_vehicle_category(
    category_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    services.delete_vehicle_category(category_id)


@router.get("/photos/", response_model=list[models.VehiclePhoto])
async def list_vehicle_photos(user: models.User = Depends(get_current_user)) -> list[models.VehiclePhoto]:
    _require_permission(user, action="view")
    return services.list_vehicle_photos()


@router.post("/photos/", response_model=models.VehiclePhoto, status_code=201)
async def upload_vehicle_photo(
    file: UploadFile = File(...), user: models.User = Depends(get_current_user)
) -> models.VehiclePhoto:
    _require_permission(user, action="edit")
    if not file.content_type or not file.content_type.startswith("image/"):
        await file.close()
        raise HTTPException(status_code=400, detail="Seules les images sont autorisées.")
    try:
        return services.add_vehicle_photo(file.file, file.filename)
    finally:
        await file.close()


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_vehicle_photo(
    photo_id: int, user: models.User = Depends(get_current_user)
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_vehicle_photo(photo_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

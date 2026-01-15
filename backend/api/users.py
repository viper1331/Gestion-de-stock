"""Routes de gestion des utilisateurs pour les administrateurs."""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.auth import get_current_user
from backend.core import models, services
from backend.services import notifications

router = APIRouter()


@router.get("/", response_model=list[models.User])
async def list_users(
    include_pending: bool = True,
    current_user: models.User = Depends(get_current_user),
) -> list[models.User]:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    return services.list_users(include_pending=include_pending)


@router.post("/", response_model=models.User, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: models.UserCreate,
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        return services.create_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{user_id}", response_model=models.User)
async def update_user(
    user_id: int,
    payload: models.UserUpdate,
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        return services.update_user(user_id, payload)
    except ValueError as exc:
        message = str(exc)
        if message == "Utilisateur introuvable":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
) -> None:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        services.delete_user(user_id)
    except ValueError as exc:
        message = str(exc)
        if message == "Utilisateur introuvable":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


@router.post("/{user_id}/approve", response_model=models.User)
async def approve_user(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        user = services.approve_user(user_id, current_user)
    except ValueError as exc:
        message = str(exc)
        if message == "Utilisateur introuvable":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc
    notifications.on_user_approved(user)
    return user


@router.post("/{user_id}/reject", response_model=models.User)
async def reject_user(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autorisations insuffisantes",
        )
    try:
        return services.reject_user(user_id, current_user)
    except ValueError as exc:
        message = str(exc)
        if message == "Utilisateur introuvable":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc

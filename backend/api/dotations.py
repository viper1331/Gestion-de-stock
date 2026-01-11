"""Routes pour la gestion des collaborateurs et dotations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "dotations"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/collaborators", response_model=list[models.Collaborator])
async def list_collaborators(
    user: models.User = Depends(get_current_user),
) -> list[models.Collaborator]:
    _require_permission(user, action="view")
    return services.list_collaborators()


@router.post("/collaborators", response_model=models.Collaborator, status_code=201)
async def create_collaborator(
    payload: models.CollaboratorCreate,
    user: models.User = Depends(get_current_user),
) -> models.Collaborator:
    _require_permission(user, action="edit")
    return services.create_collaborator(payload)


@router.put("/collaborators/{collaborator_id}", response_model=models.Collaborator)
async def update_collaborator(
    collaborator_id: int,
    payload: models.CollaboratorUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Collaborator:
    _require_permission(user, action="edit")
    try:
        return services.update_collaborator(collaborator_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/collaborators/{collaborator_id}", status_code=204)
async def delete_collaborator(
    collaborator_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_collaborator(collaborator_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/collaborators/bulk-import",
    response_model=models.CollaboratorBulkImportResult,
    status_code=200,
)
async def bulk_import_collaborators(
    payload: models.CollaboratorBulkImportPayload,
    user: models.User = Depends(get_current_user),
) -> models.CollaboratorBulkImportResult:
    _require_permission(user, action="edit")
    return services.bulk_import_collaborators(payload)


@router.get("/dotations", response_model=list[models.Dotation])
async def list_dotations(
    collaborator_id: int | None = Query(default=None),
    item_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
) -> list[models.Dotation]:
    _require_permission(user, action="view")
    return services.list_dotations(collaborator_id=collaborator_id, item_id=item_id)


@router.post("/dotations", response_model=models.Dotation, status_code=201)
async def create_dotation(
    payload: models.DotationCreate,
    user: models.User = Depends(get_current_user),
) -> models.Dotation:
    _require_permission(user, action="edit")
    try:
        return services.create_dotation(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/dotations/{dotation_id}", response_model=models.Dotation)
async def update_dotation(
    dotation_id: int,
    payload: models.DotationUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Dotation:
    _require_permission(user, action="edit")
    try:
        return services.update_dotation(dotation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/dotations/{dotation_id}", status_code=204)
async def delete_dotation(
    dotation_id: int,
    restock: bool = Query(default=False, description="Réintègre les quantités au stock"),
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, action="edit")
    try:
        services.delete_dotation(dotation_id, restock=restock)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

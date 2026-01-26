"""Routes pour la gestion des collaborateurs et dotations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

COLLABORATORS_MODULE_KEY = "collaborators"
DOTATIONS_MODULE_KEY = "dotations"


def _require_permission(user: models.User, module_key: str, *, action: str) -> None:
    if not services.has_module_access(user, module_key, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_clothing_module(module: str) -> None:
    normalized = services.normalize_module_key(module)
    if normalized != "clothing":
        raise HTTPException(status_code=400, detail="Module non supporté")


@router.get("/collaborators", response_model=list[models.Collaborator])
async def list_collaborators(
    user: models.User = Depends(get_current_user),
) -> list[models.Collaborator]:
    _require_permission(user, COLLABORATORS_MODULE_KEY, action="view")
    return services.list_collaborators()


@router.post("/collaborators", response_model=models.Collaborator, status_code=201)
async def create_collaborator(
    payload: models.CollaboratorCreate,
    user: models.User = Depends(get_current_user),
) -> models.Collaborator:
    _require_permission(user, COLLABORATORS_MODULE_KEY, action="edit")
    return services.create_collaborator(payload)


@router.put("/collaborators/{collaborator_id}", response_model=models.Collaborator)
async def update_collaborator(
    collaborator_id: int,
    payload: models.CollaboratorUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Collaborator:
    _require_permission(user, COLLABORATORS_MODULE_KEY, action="edit")
    try:
        return services.update_collaborator(collaborator_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/collaborators/{collaborator_id}", status_code=204)
async def delete_collaborator(
    collaborator_id: int,
    user: models.User = Depends(get_current_user),
) -> None:
    _require_permission(user, COLLABORATORS_MODULE_KEY, action="edit")
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
    _require_permission(user, COLLABORATORS_MODULE_KEY, action="edit")
    return services.bulk_import_collaborators(payload)


@router.get("/dotations", response_model=list[models.Dotation])
async def list_dotations(
    collaborator_id: int | None = Query(default=None),
    item_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
) -> list[models.Dotation]:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="view")
    return services.list_dotations(collaborator_id=collaborator_id, item_id=item_id)


@router.post("/dotations", response_model=models.Dotation, status_code=201)
async def create_dotation(
    payload: models.DotationCreate,
    user: models.User = Depends(get_current_user),
) -> models.Dotation:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="edit")
    try:
        return services.create_dotation(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scan_add", response_model=models.Dotation, status_code=201)
async def scan_add_dotation(
    payload: models.DotationScanAddPayload,
    user: models.User = Depends(get_current_user),
) -> models.Dotation:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="edit")
    if not payload.employee_id:
        raise HTTPException(status_code=400, detail="Collaborateur manquant")
    if not payload.barcode.strip():
        raise HTTPException(status_code=400, detail="Code-barres manquant")
    try:
        return services.scan_add_dotation(
            employee_id=payload.employee_id,
            barcode=payload.barcode,
            quantity=payload.quantity,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "Aucun article" in detail or "introuvable" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.put("/dotations/{dotation_id}", response_model=models.Dotation)
async def update_dotation(
    dotation_id: int,
    payload: models.DotationUpdate,
    user: models.User = Depends(get_current_user),
) -> models.Dotation:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="edit")
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
    _require_permission(user, DOTATIONS_MODULE_KEY, action="edit")
    try:
        services.delete_dotation(dotation_id, restock=restock)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dotations/beneficiaries", response_model=list[models.DotationBeneficiary])
async def list_dotation_beneficiaries(
    module: str = Query(default="clothing"),
    user: models.User = Depends(get_current_user),
) -> list[models.DotationBeneficiary]:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="view")
    _require_clothing_module(module)
    return services.list_dotation_beneficiaries()


@router.get("/dotations/assigned-items", response_model=list[models.DotationAssignedItem])
async def list_dotation_assigned_items(
    employee_id: int = Query(..., gt=0),
    module: str = Query(default="clothing"),
    user: models.User = Depends(get_current_user),
) -> list[models.DotationAssignedItem]:
    _require_permission(user, DOTATIONS_MODULE_KEY, action="view")
    _require_clothing_module(module)
    return services.list_dotation_assigned_items(employee_id)

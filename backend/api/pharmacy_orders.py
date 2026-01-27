"""Routes pour la gestion des bons de commande pharmacie."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.admin import require_admin
from backend.api.auth import get_current_user
from backend.core import db, models, services
from backend.services.email_sender import EmailSendError
from backend.services.pdf_config import render_filename, resolve_pdf_config

router = APIRouter()

MODULE_KEY = "pharmacy"


def _require_permission(user: models.User, *, action: str) -> None:
    if user.role == "admin":
        return
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.PharmacyPurchaseOrderDetail])
async def list_orders(
    include_archived: bool = Query(False, description="Inclure les bons de commande archivés"),
    archived_only: bool = Query(False, description="Afficher uniquement les bons de commande archivés"),
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyPurchaseOrderDetail]:
    _require_permission(user, action="view")
    return services.list_pharmacy_purchase_orders(
        include_archived=include_archived,
        archived_only=archived_only,
    )


@router.post("/", response_model=models.PharmacyPurchaseOrderDetail, status_code=201)
async def create_order(
    payload: models.PharmacyPurchaseOrderCreate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="edit")
    try:
        return services.create_pharmacy_purchase_order(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=models.PharmacyPurchaseOrderDetail)
async def get_order(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="view")
    try:
        return services.get_pharmacy_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{order_id}/pdf")
async def download_order_pdf(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    _require_permission(user, action="view")
    try:
        order = services.get_pharmacy_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        resolved = resolve_pdf_config("pharmacy_orders")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf_bytes = services.generate_pharmacy_purchase_order_pdf(
        order,
        user=user,
        site_key=db.get_current_site_key(),
    )
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key="pharmacy_orders",
        module_title=resolved.module_label,
        context={"order_id": order.id, "ref": order.id},
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{order_id}", response_model=models.PharmacyPurchaseOrderDetail)
async def update_order(
    order_id: int,
    payload: models.PharmacyPurchaseOrderUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="edit")
    try:
        return services.update_pharmacy_purchase_order(order_id, payload)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/{order_id}/receive", response_model=models.PharmacyPurchaseOrderDetail)
async def receive_order(
    order_id: int,
    payload: models.PharmacyPurchaseOrderReceivePayload,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="edit")
    try:
        return services.receive_pharmacy_purchase_order(order_id, payload)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/{order_id}/archive", response_model=models.PharmacyPurchaseOrderDetail)
async def archive_order(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="edit")
    try:
        return services.archive_pharmacy_purchase_order(order_id, archived_by=user.id)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/{order_id}/unarchive", response_model=models.PharmacyPurchaseOrderDetail)
async def unarchive_order(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PharmacyPurchaseOrderDetail:
    _require_permission(user, action="edit")
    try:
        return services.unarchive_pharmacy_purchase_order(order_id)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/{order_id}/send-to-supplier", response_model=models.PurchaseOrderSendResponse)
async def send_to_supplier(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderSendResponse:
    _require_permission(user, action="edit")
    try:
        return services.send_pharmacy_purchase_order_to_supplier(
            db.get_current_site_key(),
            order_id,
            user,
        )
    except services.SupplierResolutionError as exc:
        status_code = 409 if exc.code == "SUPPLIER_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailSendError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    user: models.User = Depends(require_admin),
) -> None:
    try:
        services.delete_pharmacy_purchase_order(db.get_current_site_key(), order_id, user)
    except ValueError as exc:
        message = str(exc)
        lowered = message.lower()
        if "reçu" in lowered:
            raise HTTPException(status_code=409, detail=message) from exc
        status = 404 if "introuvable" in lowered else 400
        raise HTTPException(status_code=status, detail=message) from exc

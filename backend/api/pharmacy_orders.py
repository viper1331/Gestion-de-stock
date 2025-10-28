"""Routes pour la gestion des bons de commande pharmacie."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()

MODULE_KEY = "pharmacy"


def _require_permission(user: models.User, *, action: str) -> None:
    if user.role == "admin":
        return
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.PharmacyPurchaseOrderDetail])
async def list_orders(
    user: models.User = Depends(get_current_user),
) -> list[models.PharmacyPurchaseOrderDetail]:
    _require_permission(user, action="view")
    return services.list_pharmacy_purchase_orders()


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
    pdf_bytes = services.generate_pharmacy_purchase_order_pdf(order)
    filename = f"bon_commande_pharmacie_{order.id}.pdf"
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

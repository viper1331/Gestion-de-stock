"""Routes pour la gestion des bons de commande d'inventaire."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/", response_model=list[models.PurchaseOrderDetail])
async def list_orders(user: models.User = Depends(get_current_user)) -> list[models.PurchaseOrderDetail]:
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.list_purchase_orders()


@router.post("/", response_model=models.PurchaseOrderDetail, status_code=201)
async def create_order(
    payload: models.PurchaseOrderCreate,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.create_purchase_order(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=models.PurchaseOrderDetail)
async def get_order(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.get_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{order_id}/pdf")
async def download_order_pdf(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        order = services.get_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    pdf_bytes = services.generate_purchase_order_pdf(order)
    filename = f"bon_commande_{order.id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{order_id}", response_model=models.PurchaseOrderDetail)
async def update_order(
    order_id: int,
    payload: models.PurchaseOrderUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.update_purchase_order(order_id, payload)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/{order_id}/receive", response_model=models.PurchaseOrderDetail)
async def receive_order(
    order_id: int,
    payload: models.PurchaseOrderReceivePayload,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.receive_purchase_order(order_id, payload)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc

"""Routes pour la gestion des bons de commande d'inventaire."""
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

MODULE_KEY = "purchase_orders"


def _require_permission(user: models.User, *, action: str) -> None:
    if not services.has_module_access(user, MODULE_KEY, action=action):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/", response_model=list[models.PurchaseOrderDetail])
async def list_orders(user: models.User = Depends(get_current_user)) -> list[models.PurchaseOrderDetail]:
    _require_permission(user, action="view")
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.list_purchase_orders()


@router.post("/auto/refresh", response_model=models.PurchaseOrderAutoRefreshResponse)
async def refresh_auto_orders(
    module: str = Query(..., description="Module clé pour les BC auto"),
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderAutoRefreshResponse:
    try:
        services.resolve_auto_purchase_order_module_key(module)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not services.has_module_access(user, module, action="edit"):
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return services.refresh_auto_purchase_orders(module)


@router.post("/", response_model=models.PurchaseOrderDetail, status_code=201)
async def create_order(
    payload: models.PurchaseOrderCreate,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    _require_permission(user, action="edit")
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
    _require_permission(user, action="view")
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
    _require_permission(user, action="view")
    if user.role not in {"admin", "user"}:
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        order = services.get_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        resolved = resolve_pdf_config("purchase_orders")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pdf_bytes = services.generate_purchase_order_pdf(
        order,
        user=user,
        site_key=db.get_current_site_key(),
    )
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key="purchase_orders",
        module_title=resolved.module_label,
        context={"order_id": order.id, "ref": order.id},
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{order_id}/send-to-supplier", response_model=models.PurchaseOrderSendResponse)
async def send_to_supplier(
    order_id: int,
    payload: models.PurchaseOrderSendRequest | None = None,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderSendResponse:
    _require_permission(user, action="edit")
    try:
        return services.send_purchase_order_to_supplier(
            db.get_current_site_key(),
            order_id,
            user,
            to_email_override=payload.to_email_override if payload else None,
        )
    except services.SupplierResolutionError as exc:
        status_code = 409 if exc.code == "SUPPLIER_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailSendError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{order_id}/email-log", response_model=list[models.PurchaseOrderEmailLogEntry])
async def get_order_email_log(
    order_id: int,
    user: models.User = Depends(get_current_user),
) -> list[models.PurchaseOrderEmailLogEntry]:
    _require_permission(user, action="edit")
    try:
        services.get_purchase_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return services.list_purchase_order_email_logs(
        db.get_current_site_key(),
        order_id,
        module_key="purchase_orders",
    )


@router.put("/{order_id}", response_model=models.PurchaseOrderDetail)
async def update_order(
    order_id: int,
    payload: models.PurchaseOrderUpdate,
    user: models.User = Depends(get_current_user),
) -> models.PurchaseOrderDetail:
    _require_permission(user, action="edit")
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
    _require_permission(user, action="edit")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    try:
        return services.receive_purchase_order(order_id, payload)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "introuvable" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    user: models.User = Depends(require_admin),
) -> None:
    try:
        services.delete_purchase_order(db.get_current_site_key(), order_id, user)
    except ValueError as exc:
        message = str(exc)
        lowered = message.lower()
        if "reçu" in lowered:
            raise HTTPException(status_code=409, detail=message) from exc
        status = 404 if "introuvable" in lowered else 400
        raise HTTPException(status_code=status, detail=message) from exc

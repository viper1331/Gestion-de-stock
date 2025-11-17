"""Modèles Pydantic pour l'API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

BACKUP_WEEKDAY_INDEX: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_BACKUP_DAY_ALIASES: dict[str, str] = {
    "mon": "monday",
    "monday": "monday",
    "lundi": "monday",
    "tue": "tuesday",
    "tuesday": "tuesday",
    "mardi": "tuesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "mercredi": "wednesday",
    "thu": "thursday",
    "thursday": "thursday",
    "jeudi": "thursday",
    "fri": "friday",
    "friday": "friday",
    "vendredi": "friday",
    "sat": "saturday",
    "saturday": "saturday",
    "samedi": "saturday",
    "sun": "sunday",
    "sunday": "sunday",
    "dimanche": "sunday",
}


def _normalize_backup_day(day: str) -> str:
    normalized = day.strip().lower()
    if not normalized:
        raise ValueError("Jour de sauvegarde vide")
    normalized = _BACKUP_DAY_ALIASES.get(normalized, normalized)
    if normalized not in BACKUP_WEEKDAY_INDEX:
        raise ValueError(f"Jour de sauvegarde invalide: {day}")
    return normalized


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    exp: int
    type: str | None = None


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    role: str = Field(..., pattern=r"^(admin|user)$")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class User(UserBase):
    id: int
    is_active: bool = True


class UserUpdate(BaseModel):
    role: Optional[str] = Field(default=None, pattern=r"^(admin|user)$")
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    is_active: Optional[bool] = None


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class VehicleViewConfig(BaseModel):
    name: str
    background_photo_id: int | None = None
    background_url: str | None = None


class Category(BaseModel):
    id: int
    name: str
    sizes: list[str] = Field(default_factory=list)
    view_configs: list[VehicleViewConfig] | None = None
    image_url: str | None = None


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    sizes: list[str] = Field(default_factory=list)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    sizes: Optional[list[str]] = None


class Item(BaseModel):
    id: int
    name: str
    sku: str
    category_id: int | None = None
    size: str | None = None
    quantity: int
    low_stock_threshold: int = 0
    supplier_id: int | None = None
    remise_item_id: int | None = None
    remise_quantity: int | None = None
    image_url: str | None = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    documentation_url: str | None = None
    tutorial_url: str | None = None
    qr_token: str | None = None


class ItemCreate(BaseModel):
    name: str
    sku: str
    category_id: Optional[int] = None
    size: Optional[str] = None
    quantity: int = 0
    low_stock_threshold: int = 0
    supplier_id: Optional[int] = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    remise_item_id: Optional[int] = None
    documentation_url: Optional[str] = None
    tutorial_url: Optional[str] = None


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category_id: Optional[int] = None
    size: Optional[str] = None
    quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    supplier_id: Optional[int] = None
    image_url: Optional[str] = None
    remise_item_id: Optional[int] = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    documentation_url: Optional[str] = None
    tutorial_url: Optional[str] = None


class VehiclePhoto(BaseModel):
    id: int
    image_url: str
    uploaded_at: datetime


class VehicleViewBackgroundUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    photo_id: int | None = Field(default=None, ge=1)


class Movement(BaseModel):
    id: int
    item_id: int
    delta: int
    reason: str | None = None
    created_at: datetime


class MovementCreate(BaseModel):
    delta: int
    reason: Optional[str] = None


class VehicleQrInfo(BaseModel):
    item_id: int
    name: str
    sku: str
    category_name: str | None = None
    image_url: str | None = None
    documentation_url: str | None = None
    tutorial_url: str | None = None


class LowStockReport(BaseModel):
    item: Item
    shortage: int


class ConfigEntry(BaseModel):
    section: str
    key: str
    value: str


class BackupSchedule(BaseModel):
    enabled: bool = False
    days: list[str] = Field(default_factory=list)


    time: str = "02:00"

    @field_validator("days", mode="before")
    @classmethod
    def _coerce_days(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("Jour de sauvegarde invalide")
            day = _normalize_backup_day(raw)
            if day not in seen:
                normalized.append(day)
                seen.add(day)
        return normalized

    @field_validator("time")
    @classmethod
    def _validate_time(cls, value: str) -> str:
        datetime.strptime(value, "%H:%M")
        return value

    @model_validator(mode="after")
    def _ensure_days_when_enabled(self) -> "BackupSchedule":
        if self.enabled and not self.days:
            raise ValueError("Au moins un jour doit être sélectionné")
        return self


class BackupScheduleStatus(BackupSchedule):
    next_run: datetime | None = None
    last_run: datetime | None = None


class PullRequestInfo(BaseModel):
    number: int
    title: str
    url: str
    merged_at: datetime | None = None
    head_sha: str


class UpdateStatus(BaseModel):
    repository: str
    branch: str
    current_commit: str | None = None
    latest_pull_request: PullRequestInfo | None = None
    last_deployed_pull: int | None = None
    last_deployed_sha: str | None = None
    last_deployed_at: datetime | None = None
    pending_update: bool = False


class UpdateAvailability(BaseModel):
    pending_update: bool = False
    branch: str | None = None


class UpdateApplyResponse(BaseModel):
    updated: bool
    status: UpdateStatus


class SupplierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    contact_name: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=256)
    modules: list[str] = Field(default_factory=list)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    contact_name: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=256)
    modules: Optional[list[str]] = None


class Supplier(SupplierBase):
    id: int


class PurchaseOrder(BaseModel):
    id: int
    supplier_id: int | None = None
    status: str
    created_at: datetime
    note: str | None = None
    auto_created: bool = False


class PurchaseOrderItem(BaseModel):
    id: int
    purchase_order_id: int
    item_id: int
    quantity_ordered: int
    quantity_received: int
    item_name: str | None = None


class PurchaseOrderItemInput(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity_ordered: int = Field(..., gt=0)


class PurchaseOrderReceiveItem(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class PurchaseOrderReceivePayload(BaseModel):
    items: list[PurchaseOrderReceiveItem] = Field(default_factory=list)


class PurchaseOrderCreate(BaseModel):
    supplier_id: Optional[int] = None
    status: str = "PENDING"
    note: Optional[str] = None
    items: list[PurchaseOrderItemInput] = Field(default_factory=list)


class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


class PurchaseOrderDetail(PurchaseOrder):
    supplier_name: str | None = None
    items: list[PurchaseOrderItem] = Field(default_factory=list)


class CollaboratorBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=128)
    department: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)


class CollaboratorCreate(CollaboratorBase):
    pass


class CollaboratorUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    department: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)


class Collaborator(CollaboratorBase):
    id: int


class DotationBase(BaseModel):
    collaborator_id: int
    item_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = Field(default=None, max_length=256)
    perceived_at: date = Field(default_factory=date.today)
    is_lost: bool = False
    is_degraded: bool = False


class DotationCreate(DotationBase):
    pass


class Dotation(DotationBase):
    id: int
    allocated_at: datetime
    is_obsolete: bool = False


class DotationUpdate(BaseModel):
    collaborator_id: Optional[int] = Field(default=None, gt=0)
    item_id: Optional[int] = Field(default=None, gt=0)
    quantity: Optional[int] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=256)
    perceived_at: Optional[date] = None
    is_lost: Optional[bool] = None
    is_degraded: Optional[bool] = None


class PharmacyItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    packaging: Optional[str] = Field(default=None, max_length=128)
    barcode: Optional[str] = Field(default=None, min_length=1, max_length=64)
    quantity: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=5, ge=0)
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)
    category_id: Optional[int] = Field(default=None, gt=0)


class PharmacyItemCreate(PharmacyItemBase):
    pass


class PharmacyItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    packaging: Optional[str] = Field(default=None, max_length=128)
    barcode: Optional[str] = Field(default=None, min_length=1, max_length=64)
    quantity: Optional[int] = Field(default=None, ge=0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)
    category_id: Optional[int] = Field(default=None, gt=0)


class PharmacyItem(PharmacyItemBase):
    id: int


class BarcodeValue(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)


class PharmacyCategory(BaseModel):
    id: int
    name: str
    sizes: list[str] = Field(default_factory=list)


class PharmacyCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    sizes: list[str] = Field(default_factory=list)


class PharmacyCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    sizes: Optional[list[str]] = None


class PharmacyMovement(BaseModel):
    id: int
    pharmacy_item_id: int
    delta: int
    reason: str | None = None
    created_at: datetime


class PharmacyMovementCreate(BaseModel):
    delta: int
    reason: Optional[str] = None


class PharmacyPurchaseOrderItem(BaseModel):
    id: int
    purchase_order_id: int
    pharmacy_item_id: int
    quantity_ordered: int
    quantity_received: int
    pharmacy_item_name: str | None = None


class PharmacyPurchaseOrderItemInput(BaseModel):
    pharmacy_item_id: int = Field(..., gt=0)
    quantity_ordered: int = Field(..., gt=0)


class PharmacyPurchaseOrderReceiveItem(BaseModel):
    pharmacy_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class PharmacyPurchaseOrderReceivePayload(BaseModel):
    items: list[PharmacyPurchaseOrderReceiveItem] = Field(default_factory=list)


class PharmacyPurchaseOrder(BaseModel):
    id: int
    supplier_id: int | None = None
    status: str
    created_at: datetime
    note: str | None = None


class PharmacyPurchaseOrderDetail(PharmacyPurchaseOrder):
    supplier_name: str | None = None
    items: list[PharmacyPurchaseOrderItem] = Field(default_factory=list)


class PharmacyPurchaseOrderCreate(BaseModel):
    supplier_id: Optional[int] = None
    status: str = "PENDING"
    note: Optional[str] = None
    items: list[PharmacyPurchaseOrderItemInput] = Field(default_factory=list)


class PharmacyPurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


class ModulePermissionBase(BaseModel):
    user_id: int = Field(..., gt=0)
    module: str = Field(..., min_length=1, max_length=64)
    can_view: bool = True
    can_edit: bool = False


class ModulePermissionUpsert(ModulePermissionBase):
    pass


class ModulePermission(ModulePermissionBase):
    id: int


class ModuleDefinition(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)

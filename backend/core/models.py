"""Modèles Pydantic pour l'API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


VehicleType = str
UserStatus = Literal["active", "pending", "rejected", "disabled"]


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    role: str = Field(..., pattern=r"^(admin|user|certificateur)$")
    site_key: str | None = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class User(UserBase):
    id: int
    is_active: bool = True
    site_key: str
    email: str
    status: UserStatus = "active"
    session_version: int = 1
    created_at: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    rejected_at: str | None = None
    rejected_by: str | None = None
    notify_on_approval: bool = True
    otp_email_enabled: bool = False
    display_name: str | None = None


class SiteInfo(BaseModel):
    site_key: str
    display_name: str
    db_path: str
    is_active: bool = True


class SiteContext(BaseModel):
    assigned_site_key: str
    active_site_key: str
    override_site_key: Optional[str] = None
    sites: list[SiteInfo] | None = None


class SiteSelectionRequest(BaseModel):
    site_key: Optional[str] = None


class UserUpdate(BaseModel):
    role: Optional[str] = Field(default=None, pattern=r"^(admin|user|certificateur)$")
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    is_active: Optional[bool] = None
    site_key: Optional[str] = None


class AriPhysioPoint(BaseModel):
    bp_sys: Optional[int] = Field(default=None, ge=50, le=250)
    bp_dia: Optional[int] = Field(default=None, ge=30, le=150)
    hr: Optional[int] = Field(default=None, ge=30, le=220)
    spo2: Optional[int] = Field(default=None, ge=50, le=100)

    @model_validator(mode="after")
    def validate_bp(self) -> "AriPhysioPoint":
        if self.bp_sys is not None and self.bp_dia is not None:
            if self.bp_sys <= self.bp_dia:
                raise ValueError("La tension systolique doit être supérieure à la diastolique")
        return self


class AriPhysioInput(BaseModel):
    source: Literal["manual", "sensor"] = "manual"
    pre: Optional[AriPhysioPoint] = None
    post: Optional[AriPhysioPoint] = None
    device_id: Optional[str] = None
    captured_at: Optional[datetime] = None
    payload_json: Optional[dict] = None

    @model_validator(mode="after")
    def validate_sensor_payload(self) -> "AriPhysioInput":
        if self.source == "sensor":
            if not self.device_id and not self.payload_json:
                raise ValueError("Un device_id ou payload_json est requis pour un capteur")
        elif self.payload_json is not None:
            raise ValueError("payload_json est réservé aux sources capteur")
        return self


class AriSessionCreate(BaseModel):
    performed_at: Optional[datetime] = None
    physio: Optional[AriPhysioInput] = None


class AriSession(BaseModel):
    id: int
    performed_at: str
    created_at: str
    created_by: str
    physio: Optional[AriPhysioInput] = None


class AriMeasurementCreate(BaseModel):
    measurement_type: Literal["bp_sys", "bp_dia", "hr", "spo2"]
    value: float
    unit: Literal["mmHg", "bpm", "percent"]
    captured_at: Optional[datetime] = None
    source: Literal["manual", "sensor"] = "sensor"
    device_id: Optional[str] = None
    quality: Optional[int] = Field(default=None, ge=0, le=100)
    payload_json: Optional[dict] = None


class AriMeasurement(BaseModel):
    id: int
    session_id: int
    captured_at: str
    source: Literal["manual", "sensor"]
    device_id: Optional[str] = None
    measurement_type: Literal["bp_sys", "bp_dia", "hr", "spo2"]
    value: float
    unit: Literal["mmHg", "bpm", "percent"]
    quality: Optional[int] = None
    payload_json: Optional[str] = None
    created_at: str
    created_by: str


class AriStats(BaseModel):
    avg_hr_pre: Optional[float] = None
    avg_hr_post: Optional[float] = None
    avg_spo2_pre: Optional[float] = None
    avg_spo2_post: Optional[float] = None
    avg_bp_sys_pre: Optional[float] = None
    avg_bp_dia_pre: Optional[float] = None
    avg_bp_sys_post: Optional[float] = None
    avg_bp_dia_post: Optional[float] = None
    delta_hr_avg: Optional[float] = None
    delta_spo2_avg: Optional[float] = None
    delta_bp_sys_avg: Optional[float] = None
    delta_bp_dia_avg: Optional[float] = None


class MessageRecipientInfo(BaseModel):
    username: str
    role: str


class MessageSendRequest(BaseModel):
    category: str
    content: str
    recipients: list[str] = Field(default_factory=list)
    broadcast: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)


class MessageSendResponse(BaseModel):
    message_id: int
    recipients_count: int


class MenuOrderItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    parent_id: str | None = Field(default=None, alias="parentId", max_length=100)
    order: int = Field(ge=0)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Identifiant de menu vide")
        return trimmed

    @field_validator("parent_id")
    @classmethod
    def _normalize_parent_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        return trimmed


class MenuOrderPayload(BaseModel):
    version: int = Field(default=1, ge=1)
    items: list[MenuOrderItem] = Field(default_factory=list, max_length=200)


class MenuOrderResponse(BaseModel):
    menu_key: str
    version: int
    items: list[MenuOrderItem]


class TablePrefsPayload(BaseModel):
    prefs: dict[str, object]


class TablePrefsResponse(BaseModel):
    table_key: str
    prefs: dict[str, object]


class InboxMessage(BaseModel):
    id: int
    category: str
    content: str
    created_at: str
    sender_username: str
    sender_role: str
    is_read: bool
    is_archived: bool


class MessageRecipientReadInfo(BaseModel):
    username: str
    read_at: str | None


class SentMessage(BaseModel):
    id: int
    category: str
    content: str
    created_at: str
    recipients_total: int
    recipients_read: int
    recipients: list[MessageRecipientReadInfo] | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str | None = None
    username: str | None = None
    password: str
    remember_me: bool = False

    @model_validator(mode="after")
    def _ensure_identifier(self) -> "LoginRequest":
        identifier = self.identifier or self.username
        if not identifier:
            raise ValueError("Identifiant requis")
        self.identifier = identifier
        self.username = identifier
        return self


class RegisterRequest(BaseModel):
    otp_method: Literal["totp", "email"] = "totp"
    otp_email_enabled: bool | None = None
    email: str | None = None
    password: str
    display_name: str | None = None

    @model_validator(mode="after")
    def _normalize_otp_method(self) -> "RegisterRequest":
        if self.otp_email_enabled is not None:
            self.otp_method = "email" if self.otp_email_enabled else "totp"
        if self.otp_email_enabled is None:
            self.otp_email_enabled = self.otp_method == "email"
        return self


class RegisterResponse(BaseModel):
    message: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetRequestResponse(BaseModel):
    ok: bool = True
    dev_reset_token: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str


class PasswordResetConfirmResponse(BaseModel):
    ok: bool = True


class LoginUserSummary(BaseModel):
    username: str
    role: str
    site_key: str | None = None


class TotpRequiredResponse(BaseModel):
    status: Literal["totp_required"] = "totp_required"
    challenge_token: str
    user: LoginUserSummary
    needs_email_upgrade: bool | None = None


class TwoFactorRequiredResponse(BaseModel):
    status: Literal["2fa_required"] = "2fa_required"
    method: Literal["totp", "email_otp"]
    challenge_id: str
    user: LoginUserSummary
    needs_email_upgrade: bool | None = None
    resend_cooldown_seconds: int | None = None
    dev_code: str | None = None


class TotpEnrollRequiredResponse(BaseModel):
    status: Literal["totp_enroll_required"] = "totp_enroll_required"
    challenge_token: str
    otpauth_uri: str
    secret_masked: str
    secret_plain_if_allowed: str | None = None
    user: LoginUserSummary
    needs_email_upgrade: bool | None = None


class TwoFactorChallengeResponse(BaseModel):
    status: str = "totp_required"
    requires_2fa: bool = True
    challenge_id: str
    available_methods: list[str]
    username: str
    trusted_device_supported: bool = False


class TwoFactorVerifyRequest(BaseModel):
    challenge_id: str
    code: str
    remember_device: bool = False


class TotpVerifyRequest(BaseModel):
    challenge_token: str
    code: str


class OtpEmailVerifyRequest(BaseModel):
    challenge_id: str
    code: str


class OtpEmailResendRequest(BaseModel):
    challenge_id: str


class OtpEmailResendResponse(BaseModel):
    status: Literal["resent"] = "resent"
    resend_cooldown_seconds: int
    dev_code: str | None = None


class TotpEnrollConfirmRequest(BaseModel):
    challenge_token: str
    code: str


class TwoFactorRecoveryRequest(BaseModel):
    challenge_id: str
    recovery_code: str
    remember_device: bool = False


class TwoFactorSetupStartResponse(BaseModel):
    otpauth_uri: str
    secret_masked: str


class TwoFactorSetupConfirmRequest(BaseModel):
    code: str


class TwoFactorSetupConfirmResponse(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class TokenWithUser(BaseModel):
    access_token: str
    refresh_token: str
    user: LoginUserSummary


class TwoFactorDisableRequest(BaseModel):
    password: str
    code: str


class TwoFactorStatus(BaseModel):
    enabled: bool
    confirmed_at: str | None = None


class SecuritySettings(BaseModel):
    require_totp_for_login: bool = False
    idle_logout_minutes: int = Field(60, ge=0, le=1440)
    logout_on_close: bool = False


class AdminSettingsResponse(BaseModel):
    feature_ari_enabled: bool
    ari_cert_validity_days: int
    ari_cert_expiry_warning_days: int


class AdminSettingsUpdate(BaseModel):
    feature_ari_enabled: bool | None = None
    ari_cert_validity_days: int | None = Field(default=None, ge=1)
    ari_cert_expiry_warning_days: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class FeatureFlags(BaseModel):
    feature_ari_enabled: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class DebugConfig(BaseModel):
    frontend_debug: bool = False
    backend_debug: bool = False
    inventory_debug: bool = False
    network_debug: bool = False


class VehicleViewConfig(BaseModel):
    name: str
    background_photo_id: int | None = None
    background_url: str | None = None
    pointer_mode_enabled: bool = False
    hide_edit_buttons: bool = False


class VehiclePinnedSubviewCreate(BaseModel):
    subview_id: str | int


class VehiclePinnedSubviews(BaseModel):
    vehicle_id: int
    view_id: str
    pinned: list[str]


class VehicleSubviewPin(BaseModel):
    id: int
    vehicle_id: int
    view_id: str
    subview_id: str
    x_pct: float = Field(..., ge=0.0, le=1.0)
    y_pct: float = Field(..., ge=0.0, le=1.0)
    created_at: str | None = None
    updated_at: str | None = None


class VehicleSubviewPinCreate(BaseModel):
    subview_id: str
    x_pct: float
    y_pct: float


class VehicleSubviewPinUpdate(BaseModel):
    x_pct: float
    y_pct: float


class VehicleSubviewPinList(BaseModel):
    vehicle_id: int
    view_id: str
    pins: list[VehicleSubviewPin]


class Category(BaseModel):
    id: int
    name: str
    sizes: list[str] = Field(default_factory=list)
    view_configs: list[VehicleViewConfig] | None = None
    image_url: str | None = None
    vehicle_type: VehicleType | None = None
    types: list[VehicleType] = Field(default_factory=list)
    extra: dict[str, object] = Field(default_factory=dict)


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    sizes: list[str] = Field(default_factory=list)
    vehicle_type: VehicleType | None = None
    types: list[VehicleType] | None = None
    extra: dict[str, object] | None = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    sizes: Optional[list[str]] = None
    vehicle_type: VehicleType | None = None
    types: list[VehicleType] | None = None
    extra: dict[str, object] | None = None


class Item(BaseModel):
    id: int
    name: str
    sku: str
    category_id: int | None = None
    size: str | None = None
    quantity: int
    low_stock_threshold: int = 0
    track_low_stock: bool = True
    track_stock_alerts: bool = True
    supplier_id: int | None = None
    expiration_date: date | None = None
    remise_item_id: int | None = None
    pharmacy_item_id: int | None = None
    vehicle_type: VehicleType | None = None
    category_id: int | None = None
    remise_quantity: int | None = None
    pharmacy_quantity: int | None = None
    image_url: str | None = None
    shared_file_url: str | None = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    documentation_url: str | None = None
    tutorial_url: str | None = None
    qr_token: str | None = None
    lot_id: int | None = None
    lot_name: str | None = None
    lot_names: list[str] = Field(default_factory=list)
    is_in_lot: bool = False
    applied_lot_source: str | None = None
    applied_lot_assignment_id: int | None = None
    show_in_qr: bool = True
    vehicle_type: VehicleType | None = None
    assigned_vehicle_names: list[str] = Field(default_factory=list)
    extra: dict[str, object] = Field(default_factory=dict)


class PointerTarget(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)


class ItemCreate(BaseModel):
    name: str
    sku: str
    category_id: Optional[int] = None
    size: Optional[str] = None
    quantity: int = 0
    low_stock_threshold: int = 0
    track_low_stock: bool = True
    supplier_id: Optional[int] = None
    expiration_date: Optional[date] = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    remise_item_id: Optional[int] = None
    pharmacy_item_id: Optional[int] = None
    shared_file_url: Optional[str] = None
    documentation_url: Optional[str] = None
    tutorial_url: Optional[str] = None
    lot_id: Optional[int] = None
    show_in_qr: bool = True
    vehicle_type: VehicleType | None = None
    extra: dict[str, object] | None = None


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category_id: Optional[int] = None
    size: Optional[str] = None
    quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    track_low_stock: Optional[bool] = None
    supplier_id: Optional[int] = None
    image_url: Optional[str] = None
    expiration_date: Optional[date] = None
    remise_item_id: Optional[int] = None
    pharmacy_item_id: Optional[int] = None
    position_x: float | None = Field(default=None, ge=0.0, le=1.0)
    position_y: float | None = Field(default=None, ge=0.0, le=1.0)
    shared_file_url: Optional[str] = None
    documentation_url: Optional[str] = None
    tutorial_url: Optional[str] = None
    lot_id: Optional[int] = None
    show_in_qr: Optional[bool] = None
    vehicle_type: VehicleType | None = None
    extra: dict[str, object] | None = None


class VehicleAssignmentFromRemise(BaseModel):
    remise_item_id: int = Field(..., ge=1)
    category_id: int = Field(..., ge=1)
    vehicle_type: VehicleType | None = None
    target_view: str = Field(..., min_length=1)
    position: PointerTarget
    quantity: int = Field(..., gt=0)


class VehiclePhoto(BaseModel):
    id: int
    image_url: str
    uploaded_at: datetime


class VehicleGeneralInventoryPhoto(BaseModel):
    vehicle_id: int
    side: Literal["left", "right"] = "left"
    photo_url: str | None = None


class VehicleViewBackgroundUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    photo_id: int | None = Field(default=None, ge=1)


class VehicleLotUnassign(BaseModel):
    category_id: int = Field(..., ge=1)


class VehiclePharmacyLotApply(BaseModel):
    vehicle_id: int = Field(..., ge=1)
    lot_id: int = Field(..., ge=1)
    target_view: str | None = Field(default=None, max_length=128)
    drop_position: PointerTarget | None = None


class VehiclePharmacyLotApplyResult(BaseModel):
    created_item_ids: list[int]
    created_count: int


class VehicleAppliedLot(BaseModel):
    id: int
    vehicle_id: int
    vehicle_type: str | None = None
    view: str | None = None
    source: str | None = None
    pharmacy_lot_id: int | None = None
    lot_name: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    created_at: str | None = None


class VehicleAppliedLotUpdate(BaseModel):
    position_x: float = Field(..., ge=0.0, le=1.0)
    position_y: float = Field(..., ge=0.0, le=1.0)


class VehicleAppliedLotDeleteResult(BaseModel):
    restored: bool
    lot_id: int | None = None
    items_removed: int
    deleted_assignment_id: int
    deleted_item_ids: list[int]
    deleted_items_count: int


class Movement(BaseModel):
    id: int
    item_id: int
    delta: int
    reason: str | None = None
    created_at: datetime


class MovementCreate(BaseModel):
    delta: int
    reason: Optional[str] = None


class InventoryStats(BaseModel):
    references: int
    total_stock: int
    low_stock: int
    purchase_orders_open: int
    stockouts: int


class RemiseLotBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=256)
    extra: dict[str, object] | None = None


class RemiseLotCreate(RemiseLotBase):
    pass


class RemiseLotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=256)
    extra: dict[str, object] | None = None


class RemiseLot(RemiseLotBase):
    id: int
    created_at: datetime
    image_url: str | None = None
    cover_image_url: str | None = None
    item_count: int = 0
    total_quantity: int = 0
    extra: dict[str, object] = Field(default_factory=dict)


class RemiseLotWithItems(RemiseLot):
    items: list["RemiseLotItem"] = []


class RemiseLotItemBase(BaseModel):
    remise_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class RemiseLotItemUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0)


class RemiseLotItem(RemiseLotItemBase):
    id: int
    lot_id: int
    remise_name: str
    remise_sku: str
    size: Optional[str] = None
    available_quantity: int


class PharmacyLotBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=256)
    extra: dict[str, object] | None = None


class PharmacyLotCreate(PharmacyLotBase):
    pass


class PharmacyLotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=256)
    extra: dict[str, object] | None = None


class PharmacyLot(PharmacyLotBase):
    id: int
    created_at: datetime
    image_url: str | None = None
    cover_image_url: str | None = None
    item_count: int = 0
    total_quantity: int = 0
    extra: dict[str, object] = Field(default_factory=dict)


class PharmacyLotWithItems(PharmacyLot):
    items: list["PharmacyLotItem"] = []


class PharmacyLotItemBase(BaseModel):
    pharmacy_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    compartment_name: Optional[str] = Field(default=None, max_length=64)


class PharmacyLotItemUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0)
    compartment_name: Optional[str] = Field(default=None, max_length=64)


class PharmacyLotItem(PharmacyLotItemBase):
    id: int
    lot_id: int
    pharmacy_name: str
    pharmacy_sku: str
    available_quantity: int


class VehicleQrInfo(BaseModel):
    item_id: int
    name: str
    sku: str
    category_name: str | None = None
    image_url: str | None = None
    shared_file_url: str | None = None
    documentation_url: str | None = None
    tutorial_url: str | None = None


LinkCategoryModule = Literal["vehicle_qr", "pharmacy"]


class LinkCategoryBase(BaseModel):
    module: LinkCategoryModule
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    placeholder: str | None = Field(default=None, max_length=200)
    help_text: str | None = Field(default=None, max_length=400)
    is_required: bool = False
    sort_order: int = 0
    is_active: bool = True


class LinkCategoryCreate(LinkCategoryBase):
    pass


class LinkCategoryUpdate(BaseModel):
    module: LinkCategoryModule | None = None
    key: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, min_length=1, max_length=128)
    placeholder: str | None = Field(default=None, max_length=200)
    help_text: str | None = Field(default=None, max_length=400)
    is_required: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class LinkCategory(LinkCategoryBase):
    id: int
    created_at: str | None = None
    updated_at: str | None = None


class LinkItemEntry(BaseModel):
    category_key: str = Field(..., min_length=1, max_length=64)
    url: str = ""


class LinkItemUpdate(BaseModel):
    links: list[LinkItemEntry] = Field(default_factory=list)


class LinkCategoryValue(BaseModel):
    category_key: str
    label: str
    placeholder: str | None = None
    help_text: str | None = None
    is_required: bool = False
    sort_order: int = 0
    url: str = ""


class LowStockReport(BaseModel):
    item: Item
    shortage: int


class ReportRange(BaseModel):
    start: str
    end: str
    bucket: str


class ReportKpis(BaseModel):
    in_qty: int = 0
    out_qty: int = 0
    net_qty: int = 0
    low_stock_count: int = 0
    open_orders: int = 0


class ReportMoveSeriesPoint(BaseModel):
    t: str
    in_qty: int = Field(default=0, alias="in")
    out_qty: int = Field(default=0, alias="out")

    model_config = ConfigDict(populate_by_name=True)


class ReportNetSeriesPoint(BaseModel):
    t: str
    net: int = 0


class ReportLowStockSeriesPoint(BaseModel):
    t: str
    count: int = 0


class ReportOrderSeriesPoint(BaseModel):
    t: str
    created: int = 0
    ordered: int = 0
    partial: int = 0
    received: int = 0
    cancelled: int = 0


class ReportSeries(BaseModel):
    moves: list[ReportMoveSeriesPoint] = Field(default_factory=list)
    net: list[ReportNetSeriesPoint] = Field(default_factory=list)
    low_stock: list[ReportLowStockSeriesPoint] = Field(default_factory=list)
    orders: list[ReportOrderSeriesPoint] = Field(default_factory=list)


class ReportTopItem(BaseModel):
    sku: str = ""
    name: str = ""
    qty: int = 0


class ReportTops(BaseModel):
    out: list[ReportTopItem] = Field(default_factory=list)
    in_: list[ReportTopItem] = Field(default_factory=list, alias="in")

    model_config = ConfigDict(populate_by_name=True)


class ReportDataQuality(BaseModel):
    missing_sku: int = 0
    missing_supplier: int = 0
    missing_threshold: int = 0
    abnormal_movements: int = 0


class ReportOverview(BaseModel):
    module: str
    range: ReportRange
    kpis: ReportKpis
    series: ReportSeries
    tops: ReportTops
    data_quality: ReportDataQuality


class ConfigEntry(BaseModel):
    section: str
    key: str
    value: str


class QolSettings(BaseModel):
    timezone: str
    date_format: str
    auto_archive_days: int | None = None
    note_preview_length: int


class LayoutItem(BaseModel):
    i: str
    x: int
    y: int
    w: int
    h: int
    hidden: bool = False


class UserLayout(BaseModel):
    version: int = 1
    page_id: str
    layouts: dict[str, list[LayoutItem]] = Field(default_factory=dict)

    @field_validator("layouts")
    @classmethod
    def _validate_layouts(cls, value: dict[str, list[LayoutItem]]) -> dict[str, list[LayoutItem]]:
        if not isinstance(value, dict):
            raise ValueError("Mise en page invalide")
        for key, items in value.items():
            if key not in {"lg", "md", "sm"}:
                raise ValueError("Point de rupture invalide")
            if not isinstance(items, list):
                raise ValueError("Mise en page invalide")
        return value


class PageLayoutItem(BaseModel):
    i: str
    x: int
    y: int
    w: int
    h: int


class UserPageLayoutPayload(BaseModel):
    layout: dict[str, list[PageLayoutItem]] = Field(default_factory=dict)
    hidden_blocks: list[str] = Field(default_factory=list, alias="hiddenBlocks")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("layout")
    @classmethod
    def _validate_layouts(
        cls, value: dict[str, list[PageLayoutItem]]
    ) -> dict[str, list[PageLayoutItem]]:
        if not isinstance(value, dict):
            raise ValueError("Mise en page invalide")
        for key, items in value.items():
            if key not in {"lg", "md", "sm", "xs"}:
                raise ValueError("Point de rupture invalide")
            if not isinstance(items, list):
                raise ValueError("Mise en page invalide")
        return value


class UserPageLayoutResponse(UserPageLayoutPayload):
    page_key: str = Field(alias="pageKey")
    updated_at: str | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)

class BackupSchedule(BaseModel):
    enabled: bool = False
    days: list[str] = Field(default_factory=list)

    times: list[str] = Field(default_factory=lambda: ["02:00"])

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

    @field_validator("times", mode="before")
    @classmethod
    def _validate_times(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("Heure de sauvegarde invalide")

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("Heure de sauvegarde invalide")
            time_value = raw.strip()
            if not time_value:
                raise ValueError("Heure de sauvegarde vide")
            datetime.strptime(time_value, "%H:%M")
            if time_value not in seen:
                normalized.append(time_value)
                seen.add(time_value)
        return normalized

    @model_validator(mode="after")
    def _ensure_days_when_enabled(self) -> "BackupSchedule":
        if self.enabled:
            if not self.days:
                raise ValueError("Au moins un jour doit être sélectionné")
            if not self.times:
                raise ValueError("Au moins une heure doit être sélectionnée")
        return self


class BackupScheduleStatus(BackupSchedule):
    next_run: datetime | None = None
    last_run: datetime | None = None


class BackupSettings(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(ge=1)
    retention_count: int = Field(ge=1)


class BackupSettingsStatus(BackupSettings):
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
    previous_deployed_pull: int | None = None
    previous_deployed_sha: str | None = None
    previous_deployed_at: datetime | None = None
    pending_update: bool = False
    can_revert: bool = False


class UpdateAvailability(BaseModel):
    pending_update: bool = False
    branch: str | None = None


class UpdateApplyResponse(BaseModel):
    updated: bool
    status: UpdateStatus


class AboutVersionInfo(BaseModel):
    label: str
    branch: str
    last_update: datetime | None = None
    source_commit: str | None = None
    pending_update: bool = False


class AboutInfo(BaseModel):
    summary: str
    license: str
    version: AboutVersionInfo


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
    parent_id: int | None = None
    replacement_for_line_id: int | None = None
    kind: Literal["standard", "replacement_request"] = "standard"
    status: str
    created_at: datetime
    note: str | None = None
    auto_created: bool = False
    last_sent_at: datetime | None = None
    last_sent_to: str | None = None
    last_sent_by: str | None = None
    replacement_sent_at: datetime | None = None
    replacement_closed_at: datetime | None = None
    replacement_closed_by: str | None = None
    is_archived: bool = False
    archived_at: datetime | None = None
    archived_by: int | None = None


class PurchaseOrderItem(BaseModel):
    id: int
    purchase_order_id: int
    item_id: int
    quantity_ordered: int
    quantity_received: int
    item_name: str | None = None
    sku: str | None = None
    size: str | None = None
    unit: str | None = None
    nonconformity_reason: str | None = None
    is_nonconforme: bool = False
    beneficiary_employee_id: int | None = None
    beneficiary_name: str | None = None
    line_type: Literal["standard", "replacement"] = "standard"
    return_expected: bool = False
    return_reason: str | None = None
    return_employee_item_id: int | None = None
    target_dotation_id: int | None = None
    return_qty: int = 0
    return_status: Literal["none", "to_prepare", "shipped", "supplier_received", "cancelled"] = "none"
    received_conforme_qty: int = 0
    received_non_conforme_qty: int = 0


class PurchaseOrderItemInput(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity_ordered: int = Field(..., gt=0)
    beneficiary_employee_id: int | None = Field(default=None, gt=0)
    line_type: Literal["standard", "replacement"] = "standard"
    return_expected: bool = False
    return_reason: str | None = Field(default=None, max_length=256)
    return_employee_item_id: int | None = Field(default=None, gt=0)
    target_dotation_id: int | None = Field(default=None, gt=0)
    return_qty: int | None = Field(default=None, gt=0)


class PurchaseOrderReceiveItem(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class PurchaseOrderReceiveLine(BaseModel):
    line_id: int = Field(..., gt=0)
    qty: int = Field(..., gt=0)


class PurchaseOrderReceivePayload(BaseModel):
    items: list[PurchaseOrderReceiveItem] = Field(default_factory=list)
    lines: list[PurchaseOrderReceiveLine] = Field(default_factory=list)


class PurchaseOrderReceipt(BaseModel):
    id: int
    site_key: str
    purchase_order_id: int
    purchase_order_line_id: int
    module: str | None = None
    received_qty: int
    conformity_status: Literal["conforme", "non_conforme"]
    nonconformity_reason: str | None = None
    nonconformity_action: Literal["replacement", "credit_note", "return_to_supplier"] | None = None
    note: str | None = None
    created_by: str | None = None
    created_at: datetime


class PurchaseOrderNonconformity(BaseModel):
    id: int
    site_key: str
    module: str
    purchase_order_id: int
    purchase_order_line_id: int
    receipt_id: int
    status: Literal["open", "replacement_requested", "closed"]
    reason: str
    note: str | None = None
    requested_replacement: bool = False
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PurchaseOrderReceiveLinePayload(BaseModel):
    purchase_order_line_id: int = Field(..., gt=0)
    received_qty: int = Field(..., gt=0)
    conformity_status: Literal["conforme", "non_conforme"]
    nonconformity_reason: str | None = Field(default=None, max_length=256)
    nonconformity_action: Literal["replacement", "credit_note", "return_to_supplier"] | None = None
    note: str | None = Field(default=None, max_length=256)


class PurchaseOrderReceiveLineResponse(BaseModel):
    ok: bool
    line_id: int
    received_conforme_qty: int
    received_non_conforme_qty: int
    blocked_assignment: bool


class PendingClothingAssignment(BaseModel):
    id: int
    site_key: str
    purchase_order_id: int
    purchase_order_line_id: int
    receipt_id: int
    employee_id: int
    new_item_id: int
    new_item_sku: str | None = None
    new_item_size: str | None = None
    qty: int
    return_employee_item_id: int | None = None
    target_dotation_id: int | None = None
    return_reason: str | None = None
    status: Literal["pending", "validated", "cancelled"]
    created_at: datetime
    validated_at: datetime | None = None
    validated_by: str | None = None
    source_receipt: PurchaseOrderReceipt | None = None


class ClothingSupplierReturn(BaseModel):
    id: int
    site_key: str
    purchase_order_id: int
    purchase_order_line_id: int | None = None
    employee_id: int | None = None
    employee_item_id: int | None = None
    item_id: int | None = None
    qty: int
    reason: str | None = None
    status: Literal["prepared", "shipped", "supplier_received"]
    created_at: datetime


class RegisterClothingSupplierReturnPayload(BaseModel):
    purchase_order_line_id: int = Field(..., gt=0)
    employee_id: int | None = Field(default=None, gt=0)
    employee_item_id: int | None = Field(default=None, gt=0)
    item_id: int | None = Field(default=None, gt=0)
    qty: int = Field(..., gt=0)
    reason: str | None = Field(default=None, max_length=256)
    status: Literal["prepared", "shipped", "supplier_received"] = "prepared"


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
    supplier_email: str | None = None
    supplier_email_resolved: str | None = None
    supplier_has_email: bool = False
    supplier_missing_reason: str | None = None
    replacement_flow_status: Literal["none", "open", "closed"] = "none"
    replacement_flow_open: bool = False
    replacement_lock_reception: bool = False
    replacement_assignment_completed: bool = False
    items: list[PurchaseOrderItem] = Field(default_factory=list)
    receipts: list[PurchaseOrderReceipt] = Field(default_factory=list)
    nonconformities: list[PurchaseOrderNonconformity] = Field(default_factory=list)
    pending_assignments: list[PendingClothingAssignment] = Field(default_factory=list)
    supplier_returns: list[ClothingSupplierReturn] = Field(default_factory=list)


class PurchaseOrderReplacementRequest(BaseModel):
    line_id: int = Field(..., gt=0)
    receipt_id: int = Field(..., gt=0)


class PurchaseOrderReplacementResponse(BaseModel):
    ok: bool
    nonconformity_id: int
    status: Literal["open", "replacement_requested", "closed"]


class PurchaseOrderReplacementOrderResponse(BaseModel):
    replacement_order_id: int
    replacement_order_status: str
    can_send_to_supplier: bool


class PurchaseOrderEmailLogEntry(BaseModel):
    id: int
    created_at: str
    site_key: str
    module_key: str
    purchase_order_id: int
    purchase_order_number: str | None = None
    supplier_id: int | None = None
    supplier_email: str
    user_id: int | None = None
    user_email: str | None = None
    status: Literal["sent", "failed"]
    message_id: str | None = None
    error_message: str | None = None


class PurchaseOrderSendRequest(BaseModel):
    to_email_override: str | None = None
    context_note: str | None = Field(default=None, max_length=512)


class PurchaseOrderSendResponse(BaseModel):
    status: Literal["sent", "failed"]
    sent_to: str
    sent_at: str
    message_id: str | None = None


class PurchaseOrderAutoRefreshResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    items_below_threshold: int
    purchase_order_id: int | None = None


class PurchaseSuggestionLine(BaseModel):
    id: int
    suggestion_id: int
    item_id: int
    sku: str | None = None
    label: str | None = None
    variant_label: str | None = None
    qty_suggested: int
    qty_final: int
    unit: str | None = None
    reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    expiry_date: str | None = None
    expiry_days_left: int | None = None
    reason_label: str | None = None
    stock_current: int
    threshold: int


class PurchaseSuggestion(BaseModel):
    id: int
    site_key: str
    module_key: str
    supplier_id: int | None = None
    supplier_name: str | None = None
    supplier_display: str | None = None
    supplier_email: str | None = None
    supplier_status: Literal["ok", "missing", "inactive", "no_email"] | None = None
    status: Literal["draft", "converted", "dismissed"]
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class PurchaseSuggestionDetail(PurchaseSuggestion):
    lines: list[PurchaseSuggestionLine] = Field(default_factory=list)


class PurchaseSuggestionLineUpdate(BaseModel):
    id: int = Field(..., gt=0)
    qty_final: int | None = Field(default=None, ge=0)
    remove: bool = False


class PurchaseSuggestionUpdatePayload(BaseModel):
    lines: list[PurchaseSuggestionLineUpdate] = Field(default_factory=list)


class PurchaseSuggestionRefreshPayload(BaseModel):
    module_keys: list[str] = Field(default_factory=list)


class PurchaseSuggestionConvertResult(BaseModel):
    suggestion_id: int
    purchase_order_id: int
    module_key: str


class RemisePurchaseOrder(BaseModel):
    id: int
    supplier_id: int | None = None
    supplier_name: str | None = None
    status: str
    created_at: datetime
    note: str | None = None
    auto_created: bool = False
    is_archived: bool = False
    archived_at: datetime | None = None
    archived_by: int | None = None


class RemisePurchaseOrderItem(BaseModel):
    id: int
    purchase_order_id: int
    remise_item_id: int
    quantity_ordered: int
    quantity_received: int
    item_name: str | None = None
    sku: str | None = None
    unit: str | None = None


class RemisePurchaseOrderItemInput(BaseModel):
    remise_item_id: int = Field(..., gt=0)
    quantity_ordered: int = Field(..., gt=0)


class RemisePurchaseOrderReceiveItem(BaseModel):
    remise_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class RemisePurchaseOrderReceiveLine(BaseModel):
    line_id: int = Field(..., gt=0)
    qty: int = Field(..., gt=0)


class RemisePurchaseOrderReceivePayload(BaseModel):
    items: list[RemisePurchaseOrderReceiveItem] = Field(default_factory=list)
    lines: list[RemisePurchaseOrderReceiveLine] = Field(default_factory=list)


class RemisePurchaseOrderCreate(BaseModel):
    supplier_id: int | None = None
    status: str = Field(default="PENDING")
    note: str | None = None
    items: list[RemisePurchaseOrderItemInput] = Field(default_factory=list)


class RemisePurchaseOrderUpdate(BaseModel):
    supplier_id: int | None = None
    status: str | None = None
    note: str | None = None


class RemisePurchaseOrderDetail(RemisePurchaseOrder):
    supplier_email: str | None = None
    supplier_email_resolved: str | None = None
    supplier_has_email: bool = False
    supplier_missing_reason: str | None = None
    supplier_missing: bool = False
    items: list[RemisePurchaseOrderItem] = Field(default_factory=list)


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


class CollaboratorBulkImportRow(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=128)
    department: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)


class CollaboratorBulkImportPayload(BaseModel):
    mode: Literal["create", "upsert", "skip_duplicates"]
    rows: list[CollaboratorBulkImportRow]


class CollaboratorBulkImportError(BaseModel):
    rowIndex: int
    message: str


class CollaboratorBulkImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[CollaboratorBulkImportError] = Field(default_factory=list)


class DotationBase(BaseModel):
    collaborator_id: int
    item_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = Field(default=None, max_length=256)
    perceived_at: date = Field(default_factory=date.today)
    is_lost: bool = False
    is_degraded: bool = False
    degraded_qty: int = Field(default=0, ge=0)
    lost_qty: int = Field(default=0, ge=0)


class DotationCreate(DotationBase):
    pass


class Dotation(DotationBase):
    id: int
    allocated_at: datetime
    is_obsolete: bool = False
    size_variant: Optional[str] = None


class DotationUpdate(BaseModel):
    collaborator_id: Optional[int] = Field(default=None, gt=0)
    item_id: Optional[int] = Field(default=None, gt=0)
    quantity: Optional[int] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=256)
    perceived_at: Optional[date] = None
    is_lost: Optional[bool] = None
    is_degraded: Optional[bool] = None
    degraded_qty: Optional[int] = Field(default=None, ge=0)
    lost_qty: Optional[int] = Field(default=None, ge=0)


class DotationEvent(BaseModel):
    id: int
    dotation_id: int
    event_type: str
    order_id: int | None = None
    item_id: int | None = None
    item_name: str | None = None
    sku: str | None = None
    size: str | None = None
    quantity: int | None = None
    reason: str | None = None
    message: str
    created_at: datetime


class DotationBeneficiary(BaseModel):
    employee_id: int
    display_name: str
    assigned_count: int


class DotationAssignee(BaseModel):
    employee_id: int
    display_name: str
    count: int


class DotationAssigneesResponse(BaseModel):
    assignees: list[DotationAssignee]


class DotationAssignedItem(BaseModel):
    assignment_id: int
    item_id: int
    sku: str
    label: str
    variant: Optional[str] = None
    qty: int


class DotationAssigneeItem(BaseModel):
    assignment_id: int
    item_id: int
    sku: str
    name: str
    size_variant: Optional[str] = None
    qty: int
    is_lost: bool = False
    is_degraded: bool = False
    degraded_qty: int = 0
    lost_qty: int = 0


class DotationAssigneeItemsResponse(BaseModel):
    items: list[DotationAssigneeItem]


class GlobalSearchResult(BaseModel):
    result_type: str
    entity_id: int
    label: str
    description: str | None = None
    path: str


class DotationScanAddPayload(BaseModel):
    employee_id: int = Field(..., gt=0)
    barcode: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(default=1, gt=0)


class PharmacyItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    packaging: Optional[str] = Field(default=None, max_length=128)
    size_format: Optional[str] = Field(default=None, max_length=128)
    barcode: Optional[str] = Field(default=None, min_length=1, max_length=64)
    quantity: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=5, ge=0)
    track_low_stock: bool = True
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)
    category_id: Optional[int] = Field(default=None, gt=0)
    supplier_id: Optional[int] = Field(default=None, gt=0)
    extra: dict[str, object] | None = None


class PharmacyItemCreate(PharmacyItemBase):
    pass


class PharmacyItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    packaging: Optional[str] = Field(default=None, max_length=128)
    size_format: Optional[str] = Field(default=None, max_length=128)
    barcode: Optional[str] = Field(default=None, min_length=1, max_length=64)
    quantity: Optional[int] = Field(default=None, ge=0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    track_low_stock: Optional[bool] = None
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)
    category_id: Optional[int] = Field(default=None, gt=0)
    supplier_id: Optional[int] = Field(default=None, gt=0)
    extra: dict[str, object] | None = None


class PharmacyItem(PharmacyItemBase):
    id: int
    supplier_name: Optional[str] = None
    supplier_email: Optional[str] = None
    category_sizes: Optional[str] = None
    extra: dict[str, object] = Field(default_factory=dict)


class VehicleTypeEntry(BaseModel):
    id: int
    code: str
    label: str
    is_active: bool = True
    created_at: datetime


class VehicleTypeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    is_active: bool = True


class VehicleTypeUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class CustomFieldDefinition(BaseModel):
    id: int
    scope: str
    key: str
    label: str
    field_type: str
    required: bool = False
    default_json: object | None = None
    options_json: object | None = None
    is_active: bool = True
    sort_order: int = 0


class CustomFieldDefinitionCreate(BaseModel):
    scope: str = Field(..., min_length=1, max_length=64)
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    field_type: str = Field(..., min_length=1, max_length=32)
    required: bool = False
    default_json: object | None = None
    options_json: object | None = None
    is_active: bool = True
    sort_order: int = 0


class CustomFieldDefinitionUpdate(BaseModel):
    scope: Optional[str] = Field(default=None, min_length=1, max_length=64)
    key: Optional[str] = Field(default=None, min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, min_length=1, max_length=128)
    field_type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    required: Optional[bool] = None
    default_json: object | None = None
    options_json: object | None = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class VehicleLibraryItem(BaseModel):
    item_id: int
    name: str
    sku: Optional[str] = Field(default=None, max_length=64)
    image_url: Optional[str] = None
    sources: list[str] = Field(default_factory=list)
    available_qty: dict[str, int] = Field(default_factory=dict)
    remise_item_id: int | None = None
    pharmacy_item_id: int | None = None
    vehicle_type: VehicleType | None = None
    category_id: int | None = None


class VehicleLibraryLotItem(BaseModel):
    id: int
    name: str
    sku: str | None = Field(default=None, max_length=64)
    quantity: int
    available_quantity: int
    remise_item_id: int | None = None
    pharmacy_item_id: int | None = None


class VehicleLibraryLot(BaseModel):
    lot_id: int
    name: str
    description: str | None = Field(default=None, max_length=256)
    image_url: str | None = None
    cover_image_url: str | None = None
    item_count: int = 0
    total_quantity: int = 0
    origin: str
    items: list[VehicleLibraryLotItem] = Field(default_factory=list)


class VehicleLibraryCounts(BaseModel):
    items: int = 0
    lots: int = 0


class VehicleLibraryResponse(BaseModel):
    sources: list[str] = Field(default_factory=list)
    items: list[VehicleLibraryItem] = Field(default_factory=list)
    lots: list[VehicleLibraryLot] = Field(default_factory=list)
    counts: VehicleLibraryCounts = Field(default_factory=VehicleLibraryCounts)


class BarcodeValue(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)


class BarcodeLookupItem(BaseModel):
    id: int
    name: str = Field(..., min_length=1, max_length=256)


class BarcodeCatalogEntry(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    module: str = Field(..., min_length=1, max_length=64)
    item_id: Optional[int] = Field(default=None, gt=0)


class BarcodeGeneratedEntry(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    module: str = Field(..., min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, min_length=1, max_length=256)
    item_name: str = Field(..., min_length=1, max_length=256)
    created_at: datetime
    filename: str = Field(..., min_length=1, max_length=256)
    asset_path: str = Field(..., min_length=1, max_length=512)
    modified_at: Optional[datetime] = None


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
    sku: str | None = None
    unit: str | None = None


class PharmacyPurchaseOrderItemInput(BaseModel):
    pharmacy_item_id: int = Field(..., gt=0)
    quantity_ordered: int = Field(..., gt=0)


class PharmacyPurchaseOrderReceiveItem(BaseModel):
    pharmacy_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class PharmacyPurchaseOrderReceiveLine(BaseModel):
    line_id: int = Field(..., gt=0)
    qty: int = Field(..., gt=0)


class PharmacyPurchaseOrderReceivePayload(BaseModel):
    items: list[PharmacyPurchaseOrderReceiveItem] = Field(default_factory=list)
    lines: list[PharmacyPurchaseOrderReceiveLine] = Field(default_factory=list)


class PharmacyPurchaseOrder(BaseModel):
    id: int
    supplier_id: int | None = None
    status: str
    created_at: datetime
    note: str | None = None
    auto_created: bool = False
    is_archived: bool = False
    archived_at: datetime | None = None
    archived_by: int | None = None


class PharmacyPurchaseOrderDetail(PharmacyPurchaseOrder):
    supplier_name: str | None = None
    supplier_email: str | None = None
    supplier_email_resolved: str | None = None
    supplier_has_email: bool = False
    supplier_missing_reason: str | None = None
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
    category: str = Field(..., min_length=1, max_length=64)
    is_admin_only: bool = False
    sort_order: int = Field(0, ge=0)

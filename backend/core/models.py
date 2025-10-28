"""Modèles Pydantic pour l'API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


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


class Category(BaseModel):
    id: int
    name: str


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class Item(BaseModel):
    id: int
    name: str
    sku: str
    category_id: int | None = None
    size: str | None = None
    quantity: int
    low_stock_threshold: int = 0


class ItemCreate(BaseModel):
    name: str
    sku: str
    category_id: Optional[int] = None
    size: Optional[str] = None
    quantity: int = 0
    low_stock_threshold: int = 0


class ItemUpdate(BaseModel):
    name: Optional[str]
    sku: Optional[str]
    category_id: Optional[int]
    size: Optional[str]
    quantity: Optional[int]
    low_stock_threshold: Optional[int]


class Movement(BaseModel):
    id: int
    item_id: int
    delta: int
    reason: str | None = None
    created_at: datetime


class MovementCreate(BaseModel):
    delta: int
    reason: Optional[str] = None


class LowStockReport(BaseModel):
    item: Item
    shortage: int


class ConfigEntry(BaseModel):
    section: str
    key: str
    value: str


class SupplierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    contact_name: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=256)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    contact_name: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=256)


class Supplier(SupplierBase):
    id: int


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


class DotationCreate(DotationBase):
    pass


class Dotation(DotationBase):
    id: int
    allocated_at: datetime


class PharmacyItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    quantity: int = Field(default=0, ge=0)
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)


class PharmacyItemCreate(PharmacyItemBase):
    pass


class PharmacyItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    dosage: Optional[str] = Field(default=None, max_length=64)
    quantity: Optional[int] = Field(default=None, ge=0)
    expiration_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=128)


class PharmacyItem(PharmacyItemBase):
    id: int


class ModulePermissionBase(BaseModel):
    user_id: int = Field(..., gt=0)
    module: str = Field(..., min_length=1, max_length=64)
    can_view: bool = True
    can_edit: bool = False


class ModulePermissionUpsert(ModulePermissionBase):
    pass


class ModulePermission(ModulePermissionBase):
    id: int

"""Modèles Pydantic pour l'API."""
from __future__ import annotations

from datetime import datetime
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

"""Utilities shared across vehicle inventory PDF modules."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from backend.core import models

try:  # pragma: no cover - optional dependency
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    BaseModel = models.BaseModel  # type: ignore[misc]


class VehiclePdfOptions(BaseModel):
    pointer_mode: bool = False
    hide_edit_buttons: bool = False
    theme: str = "default"
    table_fallback: bool = False


@dataclass
class VehicleViewEntry:
    key: str
    representative: models.Item
    items: list[models.Item]
    total_quantity: int
    bubble_x: float | None
    bubble_y: float | None
    anchor_x: float | None
    anchor_y: float | None

    @property
    def is_lot(self) -> bool:
        return self.representative.lot_id is not None

    def lot_label(self) -> str | None:
        if self.representative.lot_id is None:
            return None
        if self.representative.lot_name:
            return self.representative.lot_name
        return f"Lot #{self.representative.lot_id}"

    def display_name(self) -> str:
        if self.is_lot:
            base = self.lot_label() or "Lot"
            return f"{base} (Lot)"
        return self.representative.name

    def reference_label(self) -> str:
        if self.is_lot:
            return self.lot_label() or "Lot"
        return self.representative.sku or "-"

    def component_descriptions(self) -> list[str]:
        if not self.is_lot:
            return []
        descriptions: list[str] = []
        for child in self.items:
            detail = f"• {child.quantity} × {child.name}"
            if child.sku:
                detail += f" (réf. {child.sku})"
            descriptions.append(detail)
        return descriptions


class PdfBuffer(io.BytesIO):
    """In-memory buffer wired to ReportLab."""

    def build_canvas(self) -> Canvas:
        return Canvas(self, pagesize=landscape(A4))


def build_vehicle_entries(items: Iterable[models.Item]) -> list[VehicleViewEntry]:
    grouped: dict[str, list[models.Item]] = {}
    for item in items:
        key = f"lot:{item.lot_id}" if item.lot_id else f"item:{item.id}"
        grouped.setdefault(key, []).append(item)

    entries: list[VehicleViewEntry] = []
    for key, collection in grouped.items():
        representative = collection[0]
        total_quantity = sum(child.quantity for child in collection)
        entries.append(
            VehicleViewEntry(
                key=key,
                representative=representative,
                items=collection,
                total_quantity=total_quantity,
                bubble_x=representative.position_x,
                bubble_y=representative.position_y,
                anchor_x=representative.position_x,
                anchor_y=representative.position_y,
            )
        )
    return entries


def layout_dimensions(style) -> tuple[float, float, float, float, float, float]:
    page_width, page_height = landscape(A4)
    margin_left, margin_top, margin_bottom, margin_right = style.margins
    usable_width = page_width - margin_left - margin_right
    usable_height = page_height - margin_top - margin_bottom
    return margin_left, margin_top, margin_bottom, margin_right, usable_width, usable_height


def build_footer_label(generated_at: datetime, *, page_number: int, page_count: int) -> str:
    return f"Généré le {generated_at.strftime('%d/%m/%Y')} — Page {page_number}/{page_count}"

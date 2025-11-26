"""Utilities for vehicle inventory PDF rendering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from textwrap import wrap as _wrap
from typing import Iterable, Sequence

from pydantic import BaseModel
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from backend.core import models

DEFAULT_VIEW_NAME = "VUE PRINCIPALE"
_MEDIA_PREFIX = "/media/"


class VehiclePdfOptions(BaseModel):
    pointer_mode: bool = False
    hide_edit_buttons: bool = False
    theme: str = "default"
    table_fallback: bool = False


@dataclass
class VehicleViewEntry:
    key: str
    name: str
    reference: str
    quantity: int
    components: list[str]
    category_id: int | None
    category_name: str | None
    view_name: str
    bubble_x: float | None
    bubble_y: float | None
    anchor_x: float | None
    anchor_y: float | None
    icon_path: Path | None


@dataclass
class VehicleView:
    category_id: int | None
    category_name: str
    view_name: str
    background_path: Path | None
    entries: list[VehicleViewEntry]
    pointer_mode: bool
    hide_edit_buttons: bool
    has_positions: bool


class PdfBuffer(BytesIO):
    """In-memory PDF buffer that builds a ReportLab canvas."""

    def build_canvas(self) -> Canvas:
        return Canvas(self, pagesize=landscape(A4))


class PageCounter:
    def __init__(self, total_pages: int) -> None:
        self.total_pages = total_pages
        self.current_page = 1

    def advance(self) -> tuple[int, int]:
        page = self.current_page
        self.current_page += 1
        return page, self.total_pages


def normalize_view_name(name: str | None) -> str:
    if not name:
        return DEFAULT_VIEW_NAME
    normalized = name.strip()
    if not normalized:
        return DEFAULT_VIEW_NAME
    return normalized.upper()


def format_date(date_value: datetime) -> str:
    return date_value.strftime("%d/%m/%Y")


def wrap_text(text: str, width: int) -> list[str]:
    if not text:
        return []
    return _wrap(text, width)


def _resolve_media_path(url: str | None, media_root: Path | None) -> Path | None:
    if not url or not media_root:
        return None
    path_str = url
    if path_str.startswith(_MEDIA_PREFIX):
        path_str = path_str[len(_MEDIA_PREFIX) :]
    candidate = media_root / path_str
    return candidate if candidate.exists() else None


def _lot_label(item: models.Item) -> str:
    if item.lot_name:
        return item.lot_name
    if item.lot_id:
        return f"Lot #{item.lot_id}"
    return "Lot"


def _aggregate_components(items: Sequence[models.Item]) -> list[str]:
    details: list[str] = []
    for child in items:
        label = f"• {child.quantity} × {child.name}"
        if child.sku:
            label += f" (réf. {child.sku})"
        details.append(label)
    return details


def _build_entry_key(item: models.Item) -> str:
    if item.lot_id:
        return f"lot:{item.lot_id}"
    return f"item:{item.id}"


def _derive_reference(representative: models.Item) -> str:
    if representative.lot_id:
        return _lot_label(representative)
    return representative.sku or "-"


def _derive_name(representative: models.Item) -> str:
    if representative.lot_id:
        return f"{_lot_label(representative)} (Lot)"
    return representative.name


def build_vehicle_entries(
    *,
    categories: Iterable[models.Category],
    items: Iterable[models.Item],
    pointer_targets: dict[str, models.PointerTarget] | None,
    media_root: Path | None,
) -> list[VehicleView]:
    categories_by_id = {category.id: category for category in categories}
    grouped: dict[str, list[models.Item]] = {}
    for item in items:
        grouped.setdefault(_build_entry_key(item), []).append(item)

    entries: list[VehicleViewEntry] = []
    for key, collection in grouped.items():
        representative = collection[0]
        category = categories_by_id.get(representative.category_id)
        view_name = normalize_view_name(representative.size)
        anchor_x = representative.position_x
        anchor_y = representative.position_y
        if pointer_targets:
            target = pointer_targets.get(key)
            if target:
                anchor_x = target.x
                anchor_y = target.y
        entries.append(
            VehicleViewEntry(
                key=key,
                name=_derive_name(representative),
                reference=_derive_reference(representative),
                quantity=sum(child.quantity for child in collection),
                components=_aggregate_components(collection) if representative.lot_id else [],
                category_id=representative.category_id,
                category_name=category.name if category else None,
                view_name=view_name,
                bubble_x=representative.position_x,
                bubble_y=representative.position_y,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                icon_path=_resolve_media_path(representative.image_url, media_root),
            )
        )

    views: list[VehicleView] = []
    for category in categories:
        view_configs = category.view_configs or [models.VehicleViewConfig(name=DEFAULT_VIEW_NAME)]
        for config in view_configs:
            normalized_view = normalize_view_name(config.name)
            view_entries = [
                entry
                for entry in entries
                if entry.category_id == category.id and entry.view_name == normalized_view
            ]
            background = _resolve_media_path(
                config.background_url or category.image_url, media_root
            )
            has_positions = any(
                entry.bubble_x is not None and entry.bubble_y is not None for entry in view_entries
            )
            views.append(
                VehicleView(
                    category_id=category.id,
                    category_name=category.name,
                    view_name=normalized_view,
                    background_path=background,
                    entries=view_entries,
                    pointer_mode=bool(getattr(config, "pointer_mode_enabled", False)),
                    hide_edit_buttons=bool(getattr(config, "hide_edit_buttons", False)),
                    has_positions=has_positions,
                )
            )

    covered_keys = {(view.category_id, view.view_name) for view in views}
    for entry in entries:
        marker = (entry.category_id, entry.view_name)
        if marker not in covered_keys:
            views.append(
                VehicleView(
                    category_id=entry.category_id,
                    category_name=entry.category_name or "Inventaire",
                    view_name=entry.view_name,
                    background_path=None,
                    entries=[entry],
                    pointer_mode=False,
                    hide_edit_buttons=False,
                    has_positions=bool(entry.bubble_x is not None and entry.bubble_y is not None),
                )
            )
            covered_keys.add(marker)

    return views


def content_bounds(style_engine, page_width: float, page_height: float) -> tuple[float, float, float, float]:
    margin_left, margin_top, margin_bottom, margin_right = style_engine.margins
    header_height = style_engine.header_height()
    footer_height = style_engine.footer_height()
    x = margin_left
    width = page_width - margin_left - margin_right
    height = page_height - header_height - footer_height - margin_top - margin_bottom
    y = footer_height + margin_bottom
    return x, y, width, height

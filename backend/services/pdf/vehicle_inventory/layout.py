"""Render vehicle inventory PDF with modularized components."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4, landscape

from backend.core import models
from .background import draw_footer, draw_header
from .bubbles import BubblePlacement, compute_bubble_layout
from .style import PdfStyleEngine
from .table import render_table
from .utils import PdfBuffer, VehiclePdfOptions, build_vehicle_entries, layout_dimensions


def _draw_bubble(
    canvas,
    placement: BubblePlacement,
    style_engine: PdfStyleEngine,
    *,
    pointer_mode: bool,
    margin_left: float,
    margin_bottom: float,
    usable_width: float,
    usable_height: float,
) -> None:
    """Render a single bubble with labels and optional pointer anchor."""

    canvas.saveState()
    canvas.setFillColor(style_engine.color("bubble"))
    canvas.setStrokeColor(style_engine.color("muted"))
    canvas.circle(placement.x, placement.y, placement.radius, fill=1, stroke=1)

    canvas.setFont(style_engine.theme.font_family, style_engine.font_size("body"))
    canvas.setFillColor(style_engine.color("text"))
    label = placement.entry.display_name()
    canvas.drawCentredString(placement.x, placement.y + 2, label[:24])
    canvas.setFont(style_engine.theme.font_family, style_engine.font_size("small"))
    canvas.setFillColor(style_engine.color("text_muted"))
    canvas.drawCentredString(placement.x, placement.y - 8, f"Qté {placement.entry.total_quantity}")

    if pointer_mode and placement.entry.anchor_x is not None and placement.entry.anchor_y is not None:
        anchor_x = margin_left + placement.entry.anchor_x * usable_width
        anchor_y = margin_bottom + placement.entry.anchor_y * usable_height
        canvas.setStrokeColor(style_engine.color("accent"))
        canvas.setDash(2, 2)
        canvas.line(placement.x, placement.y, anchor_x, anchor_y)
    canvas.restoreState()


def _render_bubble_map(
    canvas,
    *,
    entries: list[models.Item],
    generated_at: datetime,
    style_engine: PdfStyleEngine,
    options: VehiclePdfOptions,
    pointer_targets: dict[str, models.PointerTarget] | None,
) -> bool:
    """Render the bubble map or return False if a fallback is required."""

    margin_left, margin_top, margin_bottom, margin_right, usable_width, usable_height = layout_dimensions(style_engine)
    canvas.saveState()
    canvas.setFillColor(style_engine.color("surface"))
    canvas.roundRect(
        margin_left,
        margin_bottom,
        usable_width,
        usable_height,
        radius=style_engine.border_radius,
        fill=1,
        stroke=0,
    )

    entries_view = build_vehicle_entries(entries)
    if pointer_targets:
        for entry in entries_view:
            target = pointer_targets.get(entry.key)
            if target:
                entry.anchor_x = target.x
                entry.anchor_y = target.y
    placements = compute_bubble_layout(entries_view, width=usable_width, height=usable_height, options=options)
    if options.table_fallback and len(placements) < len(entries_view):
        canvas.restoreState()
        return False

    for placement in placements:
        shifted = BubblePlacement(
            entry=placement.entry,
            x=placement.x + margin_left,
            y=placement.y + margin_bottom,
            radius=placement.radius,
        )
        _draw_bubble(
            canvas,
            shifted,
            style_engine,
            pointer_mode=options.pointer_mode,
            margin_left=margin_left,
            margin_bottom=margin_bottom,
            usable_width=usable_width,
            usable_height=usable_height,
        )
    canvas.restoreState()
    return True


def render_vehicle_inventory_pdf(
    *,
    categories: Iterable[models.Category],
    items: Iterable[models.Item],
    generated_at: datetime,
    pointer_targets: dict[str, models.PointerTarget] | None,
    options: VehiclePdfOptions,
    media_root: Path | None = None,
) -> bytes:
    """Public entry point for vehicle inventory PDF rendering."""

    buffer = PdfBuffer()
    canvas = buffer.build_canvas()
    style_engine = PdfStyleEngine(theme=options.theme)

    title = "Inventaire véhicules"
    subtitle = generated_at.strftime("Mise à jour le %d/%m/%Y")
    logo_path = None
    if media_root:
        candidate = media_root / "logo-premium.png"
        logo_path = candidate if candidate.exists() else None
    draw_header(canvas, title=title, subtitle=subtitle, style_engine=style_engine, logo_path=logo_path)

    entries_list = list(items)
    success = _render_bubble_map(
        canvas,
        entries=entries_list,
        generated_at=generated_at,
        style_engine=style_engine,
        options=options,
        pointer_targets=pointer_targets,
    )
    if not success:
        render_table(canvas, entries=build_vehicle_entries(entries_list), style_engine=style_engine)

    draw_footer(canvas, generated_at=generated_at, style_engine=style_engine, page_number=1, page_count=1)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()

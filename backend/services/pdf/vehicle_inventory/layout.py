"""Render vehicle inventory PDF with modularized components."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader

from backend.core import models
from .background import draw_background
from .bubbles import draw_bubbles
from .style import PdfStyleEngine
from .table import draw_table, paginate_entries
from .utils import (
    PageCounter,
    PdfBuffer,
    VehiclePdfOptions,
    VehicleView,
    build_vehicle_entries,
    content_bounds,
    format_date,
)


def _discover_logo(media_root: Path | None) -> Path | None:
    if not media_root:
        return None
    candidate = media_root / "logo-premium.png"
    return candidate if candidate.exists() else None


def _draw_page_background(canvas, style_engine: PdfStyleEngine) -> None:
    page_width, page_height = canvas._pagesize
    canvas.saveState()
    canvas.setFillColor(style_engine.color("background"))
    canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
    canvas.restoreState()


def _draw_header(canvas, *, style_engine: PdfStyleEngine, title: str, subtitle: str | None = None) -> None:
    page_width, page_height = canvas._pagesize
    header_height = style_engine.header_height()
    margin_left, _, _, _ = style_engine.margins

    canvas.saveState()
    canvas.setFillColor(style_engine.color("header_band"))
    canvas.rect(0, page_height - header_height, page_width, header_height, stroke=0, fill=1)

    if style_engine.logo_path and style_engine.logo_path.exists():
        logo_height = header_height - 10
        canvas.drawImage(
            ImageReader(str(style_engine.logo_path)),
            margin_left,
            page_height - header_height + 4,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )
        text_offset = logo_height + 10
    else:
        text_offset = 4

    canvas.setFillColor(style_engine.color("on_header"))
    canvas.setFont(*style_engine.font("title"))
    canvas.drawString(margin_left + text_offset, page_height - header_height / 2 + 6, title)
    if subtitle:
        canvas.setFont(*style_engine.font("subtitle"))
        canvas.drawString(margin_left + text_offset, page_height - header_height + 10, subtitle)
    canvas.restoreState()


def _draw_footer(
    canvas,
    *,
    style_engine: PdfStyleEngine,
    generated_at: datetime,
    page_number: int,
    page_count: int,
) -> None:
    _, _, margin_bottom, margin_right = style_engine.margins
    footer_label = f"Généré le {format_date(generated_at)} — Page {page_number}/{page_count}"
    canvas.saveState()
    canvas.setFont(*style_engine.font("small"))
    canvas.setFillColor(style_engine.color("muted"))
    canvas.drawRightString(canvas._pagesize[0] - margin_right, margin_bottom + style_engine.footer_height() / 2, footer_label)
    canvas.restoreState()


def _render_visual_page(
    canvas,
    *,
    view: VehicleView,
    style_engine: PdfStyleEngine,
    options: VehiclePdfOptions,
    bounds: tuple[float, float, float, float],
) -> None:
    x, y, width, height = bounds

    canvas.saveState()
    canvas.setFillColor(style_engine.color("surface"))
    canvas.roundRect(x, y, width, height, radius=8, stroke=0, fill=1)
    canvas.restoreState()

    image_bounds = draw_background(canvas, view.background_path, bounds, style_engine)
    pointer_mode = options.pointer_mode or view.pointer_mode
    draw_bubbles(canvas, view.entries, image_bounds, pointer_mode, style_engine)


def _render_table_page(
    canvas,
    *,
    view: VehicleView,
    entries,
    style_engine: PdfStyleEngine,
    bounds: tuple[float, float, float, float],
) -> None:
    section_title = f"{view.category_name} — {view.view_name}"
    draw_table(canvas, entries=entries, bounds=bounds, style_engine=style_engine, section_title=section_title)


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
    logo_path = _discover_logo(media_root)
    style_engine = PdfStyleEngine(theme=options.theme, logo_path=logo_path)
    bounds = content_bounds(style_engine, *landscape(A4))

    views = sorted(
        build_vehicle_entries(
            categories=categories,
            items=items,
            pointer_targets=pointer_targets,
            media_root=media_root,
        ),
        key=lambda view: (view.category_name, view.view_name),
    )

    page_plan: list[tuple[str, object]] = []
    for view in views:
        if view.background_photo_id and not view.background_path:
            raise FileNotFoundError("Photo de fond obligatoire manquante pour la vue")
        if not view.entries and not view.background_path:
            continue

        effective_pointer = VehiclePdfOptions(
            pointer_mode=options.pointer_mode or view.pointer_mode,
            hide_edit_buttons=True,
            theme=options.theme,
        )

        use_visual_page = (
            bool(view.background_path)
            and view.has_positions
            and not options.table_fallback
        )

        if use_visual_page:
            page_plan.append(("visual", view, effective_pointer))
        elif view.entries:
            chunks = paginate_entries(view.entries, bounds[3], style_engine)
            for chunk in chunks:
                page_plan.append(("table", view, effective_pointer, chunk))

    if not page_plan:
        raise ValueError("Aucune page générée pour l'inventaire véhicule")

    counter = PageCounter(len(page_plan))
    for entry in page_plan:
        kind = entry[0]
        _draw_page_background(canvas, style_engine)
        _draw_header(
            canvas,
            style_engine=style_engine,
            title="Inventaire véhicules",
            subtitle=f"Mise à jour le {format_date(generated_at)}",
        )
        if kind == "visual":
            _, view, view_options = entry
            _render_visual_page(canvas, view=view, style_engine=style_engine, options=view_options, bounds=bounds)
        else:
            _, view, view_options, chunk = entry
            _render_table_page(canvas, view=view, entries=chunk, style_engine=style_engine, bounds=bounds)
        page_number, page_count = counter.advance()
        _draw_footer(
            canvas,
            style_engine=style_engine,
            generated_at=generated_at,
            page_number=page_number,
            page_count=page_count,
        )
        canvas.showPage()

    canvas.save()
    return buffer.getvalue()

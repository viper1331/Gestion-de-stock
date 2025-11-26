"""Layout helpers for vehicle inventory pages."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader

from backend.core import models
from .background import BackgroundInfo, draw_background, prepare_background
from .bubbles import draw_bubbles
from .models import DocumentPlan, PageMetadata, VehiclePdfOptions, VehicleView
from .style_engine import PdfStyleEngine
from .table import draw_table, paginate_entries
from .utils import PageCounter, build_vehicle_entries, content_bounds, format_date, page_size_for_orientation


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
    if not title:
        return
    page_width, page_height = canvas._pagesize
    header_height = style_engine.header_height()
    margin_left, _, _, _ = style_engine.margins

    canvas.saveState()
    canvas.setFillColor(style_engine.color("header_band"))
    canvas.rect(0, page_height - header_height, page_width, header_height, stroke=0, fill=1)

    text_offset = 6
    canvas.setFillColor(style_engine.color("text"))
    canvas.setFont(*style_engine.font("title"))
    canvas.drawString(margin_left + text_offset, page_height - header_height / 2 + 6, title)
    if subtitle:
        canvas.setFont(*style_engine.font("subtitle"))
        canvas.setFillColor(style_engine.color("muted"))
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


def _build_document_plan(
    *,
    categories: Iterable[models.Category],
    items: Iterable[models.Item],
    generated_at: datetime,
    pointer_targets: dict[str, models.PointerTarget] | None,
    options: VehiclePdfOptions,
    media_root: Path | None = None,
) -> DocumentPlan:
    views = sorted(
        build_vehicle_entries(
            categories=categories,
            items=items,
            pointer_targets=pointer_targets,
            media_root=media_root,
        ),
        key=lambda view: (view.category_name, view.view_name),
    )

    plan = DocumentPlan(generated_at=generated_at)
    for view in views:
        if view.background_photo_id and not view.background_path:
            raise FileNotFoundError("Photo de fond obligatoire manquante pour la vue")
        if not view.entries and not view.background_path:
            continue

        effective_pointer = VehiclePdfOptions(
            pointer_mode_enabled=options.pointer_mode_enabled or view.pointer_mode,
            hide_edit_buttons=True,
            theme=options.theme,
            include_footer=options.include_footer,
            include_header=options.include_header,
            table_fallback=options.table_fallback,
        )

        use_visual_page = (
            bool(view.background_path)
            and view.has_positions
            and not options.table_fallback
        )

        if use_visual_page:
            orientation = "landscape"
            if view.background_path:
                try:
                    orientation = prepare_background(view.background_path).orientation
                except FileNotFoundError:
                    orientation = "landscape"
            plan.add(PageMetadata(kind="visual", view=view, pointer_options=effective_pointer, entries=None, orientation=orientation))
        elif view.entries:
            orientation = "landscape"
            plan_pages = paginate_entries(view.entries, A4[1], PdfStyleEngine(theme=options.theme))
            for chunk in plan_pages:
                plan.add(PageMetadata(kind="table", view=view, pointer_options=effective_pointer, entries=chunk, orientation=orientation))

    if not plan.pages:
        raise ValueError("Aucune page générée pour l'inventaire véhicule")
    return plan


def render_page(canvas, page: PageMetadata, *, style_engine: PdfStyleEngine) -> None:
    bounds = content_bounds(style_engine, *canvas._pagesize)
    _draw_page_background(canvas, style_engine)
    _draw_header(
        canvas,
        style_engine=style_engine,
        title="Inventaire véhicules" if page.pointer_options.include_header else "",
        subtitle=None,
    )
    if page.kind == "visual":
        view = page.view
        background_info = prepare_background(view.background_path) if view.background_path else None
        image_bounds = draw_background(canvas, background_info, bounds, style_engine) if background_info else bounds
        pointer_mode = page.pointer_options.pointer_mode_enabled or view.pointer_mode
        draw_bubbles(canvas, view.entries, image_bounds, pointer_mode, style_engine)
    else:
        section_title = f"{page.view.category_name} — {page.view.view_name}"
        draw_table(canvas, entries=page.entries or [], bounds=bounds, style_engine=style_engine, section_title=section_title)


def build_plan(*, categories, items, generated_at, pointer_targets, options, media_root) -> DocumentPlan:
    return _build_document_plan(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=options,
        media_root=media_root,
    )

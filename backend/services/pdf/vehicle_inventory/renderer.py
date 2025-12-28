"""Vehicle inventory PDF renderer entry point."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import logging

from backend.core import models
from backend.core.config import settings
from .html_renderer import render_vehicle_inventory_pdf_html_sync
from .layout import build_plan, render_page
from .models import VehiclePdfOptions
from .playwright_support import (
    PLAYWRIGHT_OK,
    RENDERER_AUTO,
    RENDERER_HTML,
    RENDERER_REPORTLAB,
    build_playwright_error_message,
    check_playwright_status,
    log_playwright_context,
    resolve_renderer_mode,
)
from .style_engine import PdfStyleEngine
from .utils import PageCounter, PdfBuffer, format_date, page_size_for_orientation

logger = logging.getLogger(__name__)


class PlaywrightPdfError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


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

    diagnostics = check_playwright_status()
    renderer_mode = resolve_renderer_mode(diagnostics)

    if renderer_mode == RENDERER_HTML:
        if diagnostics.status != PLAYWRIGHT_OK:
            log_playwright_context(diagnostics.status)
            message = build_playwright_error_message(diagnostics.status)
            raise PlaywrightPdfError(diagnostics.status, message)
        try:
            return render_vehicle_inventory_pdf_html_sync(
                categories=categories,
                items=items,
                generated_at=generated_at,
                pointer_targets=pointer_targets,
                options=options,
                media_root=media_root,
            )
        except RuntimeError as exc:
            if settings.PDF_RENDERER != RENDERER_AUTO:
                raise
            logger.warning("Falling back to ReportLab PDF renderer: %s", exc)
        except Exception as exc:
            if settings.PDF_RENDERER != RENDERER_AUTO:
                raise
            logger.warning("Falling back to ReportLab PDF renderer: %s", exc)

    if settings.PDF_RENDERER == RENDERER_AUTO and renderer_mode == RENDERER_REPORTLAB:
        log_playwright_context(diagnostics.status)
        logger.warning(
            "Falling back to ReportLab PDF renderer (status=%s): %s",
            diagnostics.status,
            build_playwright_error_message(diagnostics.status),
        )

    buffer = PdfBuffer()
    canvas = buffer.build_canvas()
    plan = build_plan(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=options,
        media_root=media_root,
    )

    counter = PageCounter(len(plan.pages))
    for page in plan:
        canvas.setPageSize(page_size_for_orientation(page.orientation))
        style_engine = PdfStyleEngine(theme=options.theme, logo_path=None)
        render_page(canvas, page, style_engine=style_engine)
        page_number, page_count = counter.advance()
        if options.include_footer:
            canvas.saveState()
            _, _, margin_bottom, margin_right = style_engine.margins
            vehicle_label = page.view.category_name or "Véhicule"
            footer_label = f"Généré le {format_date(generated_at)} — Page {page_number}/{page_count} — {vehicle_label}"
            canvas.setFont(*style_engine.font("small"))
            canvas.setFillColor(style_engine.color("muted"))
            canvas.drawRightString(canvas._pagesize[0] - margin_right, margin_bottom + style_engine.footer_height() / 2, footer_label)
            canvas.restoreState()
        canvas.showPage()

    canvas.save()
    return buffer.getvalue()

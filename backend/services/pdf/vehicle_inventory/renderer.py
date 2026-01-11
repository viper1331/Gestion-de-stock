"""Vehicle inventory PDF renderer entry point."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
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
    cancel_check: Callable[[], None] | None = None,
) -> bytes:
    """Public entry point for vehicle inventory PDF rendering."""

    start_time = time.perf_counter()
    diagnostics = check_playwright_status()
    renderer_mode = resolve_renderer_mode(diagnostics)
    if cancel_check:
        cancel_check()

    if renderer_mode == RENDERER_HTML:
        if diagnostics.status != PLAYWRIGHT_OK:
            log_playwright_context(diagnostics.status)
            message = build_playwright_error_message(diagnostics.status)
            raise PlaywrightPdfError(diagnostics.status, message)
        try:
            if cancel_check:
                cancel_check()
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
    style_engine = PdfStyleEngine(theme=options.theme, logo_path=None)
    plan_start = time.perf_counter()
    if cancel_check:
        cancel_check()
    plan = build_plan(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=options,
        media_root=media_root,
    )
    plan_end = time.perf_counter()

    counter = PageCounter(len(plan.pages))
    render_start = time.perf_counter()
    for page in plan:
        if cancel_check:
            cancel_check()
        canvas.setPageSize(page_size_for_orientation(page.orientation))
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

    render_end = time.perf_counter()
    canvas.save()
    pdf_bytes = buffer.getvalue()
    total_time = time.perf_counter()
    logger.info(
        "[vehicle_inventory_pdf] plan_ms=%.2f render_ms=%.2f total_ms=%.2f size_bytes=%s",
        (plan_end - plan_start) * 1000,
        (render_end - render_start) * 1000,
        (total_time - start_time) * 1000,
        len(pdf_bytes),
    )
    return pdf_bytes

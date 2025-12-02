"""Vehicle inventory PDF renderer entry point."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from backend.core import models
from .layout import build_plan, render_page
from .models import VehiclePdfOptions
from .style_engine import PdfStyleEngine
from .utils import PageCounter, PdfBuffer, format_date, page_size_for_orientation


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
            footer_label = f"Généré le {format_date(generated_at)} — Page {page_number}/{page_count}"
            canvas.setFont(*style_engine.font("small"))
            canvas.setFillColor(style_engine.color("muted"))
            canvas.drawRightString(canvas._pagesize[0] - margin_right, margin_bottom + style_engine.footer_height() / 2, footer_label)
            canvas.restoreState()
        canvas.showPage()

    canvas.save()
    return buffer.getvalue()

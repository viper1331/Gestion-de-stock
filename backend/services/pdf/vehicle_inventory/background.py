"""Decorative primitives for PDF pages."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.utils import ImageReader

from .utils import build_footer_label


def draw_header(canvas, *, title: str, subtitle: str | None, style_engine, logo_path: Path | None = None):
    margin_left, margin_top, _, _, _, _ = (style_engine.margins)
    canvas.setFont(style_engine.theme.font_family, style_engine.font_size("title"))
    canvas.setFillColor(style_engine.color("text"))
    canvas.drawString(margin_left, canvas._pagesize[1] - margin_top + 10, title)
    if subtitle:
        canvas.setFont(style_engine.theme.font_family, style_engine.font_size("subtitle"))
        canvas.setFillColor(style_engine.color("text_muted"))
        canvas.drawString(margin_left, canvas._pagesize[1] - margin_top + -2, subtitle)

    if logo_path and logo_path.exists():
        image = ImageReader(str(logo_path))
        canvas.drawImage(image, canvas._pagesize[0] - margin_left - 50, canvas._pagesize[1] - margin_top, width=45, height=45, mask='auto')


def draw_footer(canvas, *, generated_at: datetime, style_engine, page_number: int, page_count: int):
    footer = build_footer_label(generated_at, page_number=page_number, page_count=page_count)
    canvas.setFont(style_engine.theme.font_family, style_engine.font_size("small"))
    canvas.setFillColor(style_engine.color("text_muted"))
    canvas.drawRightString(canvas._pagesize[0] - style_engine.margins[3], style_engine.margins[2] - 4, footer)

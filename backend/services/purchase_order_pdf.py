"""Rendu PDF des bons de commande."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Callable

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.core import models
from backend.services.pdf_config import (
    draw_watermark,
    effective_density_scale,
    margins_for_format,
    page_size_for_format,
    resolve_pdf_config,
)
from backend.services.pdf.theme import apply_theme_reportlab, resolve_reportlab_theme, scale_reportlab_theme


def _resolve_module_key(purchase_order: models.PurchaseOrderDetail) -> str:
    if isinstance(purchase_order, models.RemisePurchaseOrderDetail):
        return "remise_orders"
    if isinstance(purchase_order, models.PharmacyPurchaseOrderDetail):
        return "pharmacy_orders"
    return "purchase_orders"


def _resolve_font(font_family: str, variant: str) -> str:
    candidate = f"{font_family}-{variant}"
    if candidate in pdfmetrics.getRegisteredFontNames():
        return candidate
    return font_family


def _format_value(value: str | None) -> str:
    if value is None:
        return "—"
    trimmed = value.strip()
    return trimmed if trimmed else "—"


def _wrap_text(value: str, max_width: float, font_name: str, font_size: float) -> list[str]:
    words = value.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if pdfmetrics.stringWidth(word, font_name, font_size) <= max_width:
            current = word
            continue
        chunk = ""
        for char in word:
            if pdfmetrics.stringWidth(chunk + char, font_name, font_size) <= max_width:
                chunk += char
            else:
                if chunk:
                    lines.append(chunk)
                chunk = char
        current = chunk
    if current:
        lines.append(current)
    return lines or [value]


def _extract_item_name(item: object) -> str:
    for attr in ("item_name", "pharmacy_item_name"):
        value = getattr(item, attr, None)
        if value:
            return str(value)
    for attr in ("item_id", "remise_item_id", "pharmacy_item_id"):
        value = getattr(item, attr, None)
        if value is not None:
            return f"Article #{value}"
    return "Article"


def render_purchase_order_pdf(
    *,
    title: str,
    purchase_order: models.PurchaseOrderDetail,
    buyer_block: dict[str, str | None],
    supplier_block: dict[str, str | None],
    delivery_block: dict[str, str | None],
    include_received: bool,
) -> bytes:
    resolved = resolve_pdf_config(_resolve_module_key(purchase_order))
    pdf_config = resolved.config
    buffer = io.BytesIO()
    page_size = page_size_for_format(pdf_config.format)
    width, height = page_size
    margin_top, margin_right, margin_bottom, margin_left = margins_for_format(pdf_config.format)
    scale = effective_density_scale(pdf_config.format)
    theme = scale_reportlab_theme(resolve_reportlab_theme(pdf_config.theme), scale)

    generated_at = datetime.now()
    title_font = _resolve_font(theme.font_family, "Bold")
    header_font = _resolve_font(theme.font_family, "Bold")

    footer_font_size = theme.base_font_size - (1 * scale)
    line_height = 12 * scale

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._page_states: list[dict[str, object]] = []

        def showPage(self) -> None:
            self._page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            self._page_states.append(dict(self.__dict__))
            page_count = len(self._page_states)
            for page_number, state in enumerate(self._page_states, start=1):
                self.__dict__.update(state)
                self._draw_footer(page_number, page_count)
                super().showPage()
            super().save()

        def _draw_footer(self, page_number: int, page_count: int) -> None:
            footer_text = f"Généré le {generated_at.strftime('%d/%m/%Y %H:%M')}"
            pdf.setFillColor(theme.muted_text_color)
            pdf.setFont(theme.font_family, footer_font_size)
            pdf.drawString(margin_left, margin_bottom - (4 * scale), footer_text)
            pdf.drawRightString(
                width - margin_right,
                margin_bottom - (4 * scale),
                f"Page {page_number}/{page_count}",
            )

    pdf = NumberedCanvas(buffer, pagesize=page_size)

    def start_page() -> float:
        apply_theme_reportlab(pdf, page_size, pdf_config.theme, scale=scale)
        draw_watermark(pdf, pdf_config, page_size, scale=scale)
        pdf.setFillColor(theme.text_color)
        y_position = height - margin_top
        pdf.setFont(title_font, theme.heading_font_size + (4 * scale))
        pdf.drawString(margin_left, y_position, title)
        y_position -= 18 * scale
        pdf.setFont(theme.font_family, theme.base_font_size + (1 * scale))
        pdf.setFillColor(theme.muted_text_color)
        pdf.drawString(margin_left, y_position, f"N° {purchase_order.id}")
        pdf.drawRightString(
            width - margin_right,
            y_position,
            purchase_order.created_at.strftime("%d/%m/%Y"),
        )
        pdf.setFillColor(theme.text_color)
        return y_position - (18 * scale)

    def ensure_space(
        y_position: float,
        needed: float,
        *,
        on_new_page: Callable[[float], float] | None = None,
    ) -> float:
        if y_position <= margin_bottom + needed:
            pdf.showPage()
            y_new = start_page()
            if on_new_page is not None:
                y_new = on_new_page(y_new)
            return y_new
        return y_position

    def draw_blocks(y_position: float) -> float:
        gap = 12 * scale
        block_width = (width - margin_left - margin_right - (2 * gap)) / 3
        block_title_height = 14 * scale
        block_font_size = theme.base_font_size - (1 * scale)
        block_padding = 6 * scale
        blocks = [
            ("Demandeur", buyer_block),
            ("Fournisseur", supplier_block),
            ("Livraison", delivery_block),
        ]
        block_lines = []
        max_lines = 1
        for _, block in blocks:
            lines: list[str] = []
            for label, value in block.items():
                line = f"{label} : {_format_value(value)}"
                lines.extend(_wrap_text(line, block_width - (2 * block_padding), theme.font_family, block_font_size))
            if not lines:
                lines = ["—"]
            max_lines = max(max_lines, len(lines))
            block_lines.append(lines)
        block_height = block_padding * 2 + block_title_height + (max_lines * line_height)
        y_position = ensure_space(y_position, block_height + (12 * scale))
        x = margin_left
        for (title_text, _), lines in zip(blocks, block_lines):
            pdf.setStrokeColor(theme.border_color)
            pdf.rect(x, y_position - block_height, block_width, block_height, stroke=1, fill=0)
            pdf.setFont(header_font, block_font_size + (1 * scale))
            pdf.drawString(x + block_padding, y_position - block_padding - (2 * scale), title_text)
            pdf.setFont(theme.font_family, block_font_size)
            text_y = y_position - block_padding - block_title_height
            for line in lines:
                pdf.drawString(x + block_padding, text_y, line)
                text_y -= line_height
            x += block_width + gap
        return y_position - block_height - (16 * scale)

    def draw_note(y_position: float) -> float:
        if not purchase_order.note:
            return y_position
        note_font_size = theme.base_font_size - (1 * scale)
        note_lines = _wrap_text(
            purchase_order.note,
            width - margin_left - margin_right,
            theme.font_family,
            note_font_size,
        )
        note_height = (len(note_lines) + 1) * line_height + (6 * scale)
        y_position = ensure_space(y_position, note_height + (6 * scale))
        pdf.setFont(header_font, note_font_size + (1 * scale))
        pdf.drawString(margin_left, y_position, "Note")
        pdf.setFont(theme.font_family, note_font_size)
        y_position -= 12 * scale
        for line in note_lines:
            pdf.drawString(margin_left, y_position, line)
            y_position -= line_height
        return y_position - (6 * scale)

    def table_columns() -> list[tuple[str, str, float, str]]:
        if include_received:
            return [
                ("sku", "SKU", 0.18, "left"),
                ("designation", "Désignation", 0.40, "left"),
                ("quantity", "Quantité", 0.12, "right"),
                ("unit", "Unité", 0.12, "left"),
                ("received", "Réceptionné", 0.18, "right"),
            ]
        return [
            ("sku", "SKU", 0.18, "left"),
            ("designation", "Désignation", 0.52, "left"),
            ("quantity", "Quantité", 0.15, "right"),
            ("unit", "Unité", 0.15, "left"),
        ]

    def draw_table_header(y_position: float) -> float:
        header_height = 18 * scale
        columns = table_columns()
        table_width = width - margin_left - margin_right
        pdf.setFillColor(theme.table_header_bg)
        pdf.rect(
            margin_left,
            y_position - header_height + (6 * scale),
            table_width,
            header_height,
            stroke=0,
            fill=1,
        )
        pdf.setFillColor(theme.table_header_text)
        pdf.setFont(header_font, theme.base_font_size)
        x = margin_left
        for _, label, ratio, align in columns:
            col_width = ratio * table_width
            if align == "right":
                pdf.drawRightString(x + col_width - (4 * scale), y_position, label)
            else:
                pdf.drawString(x + (4 * scale), y_position, label)
            x += col_width
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(
            margin_left,
            y_position - header_height + (6 * scale),
            table_width,
            header_height,
            stroke=1,
            fill=0,
        )
        pdf.setFillColor(theme.text_color)
        return y_position - header_height

    y = start_page()
    y = draw_blocks(y)
    y = draw_note(y)
    y = ensure_space(y, 30 * scale)
    y = draw_table_header(y)

    table_width = width - margin_left - margin_right
    columns = table_columns()
    row_index = 0

    for item in purchase_order.items:
        sku = _format_value(getattr(item, "sku", None))
        unit = _format_value(getattr(item, "unit", None))
        designation = _extract_item_name(item)
        quantity = str(getattr(item, "quantity_ordered", 0))
        received = str(getattr(item, "quantity_received", 0))
        row_values = {
            "sku": sku,
            "designation": designation,
            "quantity": quantity,
            "unit": unit,
            "received": received,
        }

        designation_column = next(col for col in columns if col[0] == "designation")
        designation_width = designation_column[2] * table_width - (8 * scale)
        designation_lines = _wrap_text(
            designation,
            designation_width,
            theme.font_family,
            theme.base_font_size - (1 * scale),
        )
        row_height = max(1, len(designation_lines)) * line_height + (6 * scale)
        y = ensure_space(y, row_height + (12 * scale), on_new_page=draw_table_header)

        if row_index % 2 == 1:
            pdf.setFillColor(theme.table_row_alt_bg)
            pdf.rect(
                margin_left,
                y - row_height + (6 * scale),
                table_width,
                row_height,
                stroke=0,
                fill=1,
            )
            pdf.setFillColor(theme.text_color)

        x = margin_left
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        for key, _, ratio, align in columns:
            col_width = ratio * table_width
            if key == "designation":
                text_y = y - (4 * scale)
                for line in designation_lines:
                    pdf.drawString(x + (4 * scale), text_y, line)
                    text_y -= line_height
            else:
                value = row_values.get(key, "")
                text_y = y - (4 * scale)
                if align == "right":
                    pdf.drawRightString(x + col_width - (4 * scale), text_y, value)
                else:
                    pdf.drawString(x + (4 * scale), text_y, value)
            x += col_width

        pdf.setStrokeColor(theme.border_color)
        pdf.line(margin_left, y - row_height + (6 * scale), margin_left + table_width, y - row_height + (6 * scale))
        y -= row_height
        y -= 6 * scale
        row_index += 1

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()

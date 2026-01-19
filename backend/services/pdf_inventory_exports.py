"""PDF export helpers for inventory tables."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import io

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.core import db, models, services
from backend.core.pdf_registry import pdf_module_label
from backend.services.pdf.theme import apply_theme_reportlab, resolve_reportlab_theme, scale_reportlab_theme
from backend.services.pdf_config import (
    draw_watermark,
    effective_density_scale,
    margins_for_format,
    page_size_for_format,
    resolve_pdf_config,
)

MAX_EXPORT_ROWS = 5000


@dataclass(frozen=True)
class InventoryPdfColumn:
    key: str
    label: str
    ratio: float
    align: str


def _format_date_label(value: date | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y")


def _parse_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)).date()
        except ValueError:
            return None


def _wrap_to_width(value: str, max_width: float, font_name: str, font_size: float) -> list[str]:
    def _split_long_word(word: str) -> list[str]:
        parts: list[str] = []
        current = ""
        for char in word:
            if pdfmetrics.stringWidth(current + char, font_name, font_size) <= max_width:
                current += char
            else:
                if current:
                    parts.append(current)
                current = char
        if current:
            parts.append(current)
        return parts or [word]

    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current_line = ""

    for word in words:
        word_parts = (
            _split_long_word(word)
            if pdfmetrics.stringWidth(word, font_name, font_size) > max_width
            else [word]
        )
        for part in word_parts:
            candidate = f"{current_line} {part}".strip()
            if current_line and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                lines.append(current_line)
                current_line = part
            else:
                current_line = candidate

    if current_line:
        lines.append(current_line)
    return lines or [value]


def _render_inventory_table_pdf(
    *,
    module_key: str,
    module_title: str,
    site_label: str,
    columns: list[InventoryPdfColumn],
    rows: list[dict[str, object]],
    truncated_notice: str | None = None,
) -> bytes:
    resolved = resolve_pdf_config(module_key)
    pdf_config = resolved.config
    buffer = io.BytesIO()
    page_size = page_size_for_format(pdf_config.format)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size
    margin_top, margin_right, margin_bottom, margin_left = margins_for_format(pdf_config.format)
    scale = effective_density_scale(pdf_config.format)
    line_height = 12 * scale
    header_height = 22 * scale
    row_padding = 10 * scale
    theme = scale_reportlab_theme(resolve_reportlab_theme(pdf_config.theme), scale)
    generated_at = datetime.now()

    table_width = width - margin_left - margin_right

    def draw_header() -> float:
        if not pdf_config.header.enabled:
            return height - margin_top
        title = pdf_config.header.title_template.format(
            module_title=module_title,
            module=module_key,
            generated_at=generated_at.strftime("%d/%m/%Y %H:%M"),
        )
        subtitle = pdf_config.header.subtitle_template.format(
            module_title=module_title,
            module=module_key,
            generated_at=generated_at.strftime("%d/%m/%Y %H:%M"),
        )
        pdf.setFillColor(theme.text_color)
        pdf.setFont(theme.font_family, theme.heading_font_size)
        pdf.drawString(margin_left, height - margin_top, title)
        pdf.setFont(theme.font_family, theme.base_font_size)
        pdf.setFillColor(theme.muted_text_color)
        pdf.drawString(margin_left, height - margin_top - (14 * scale), subtitle)
        pdf.drawString(margin_left, height - margin_top - (28 * scale), f"Site : {site_label}")
        pdf.setFillColor(theme.text_color)
        return height - margin_top - (42 * scale)

    def draw_footer(page_number: int) -> None:
        if not pdf_config.footer.enabled:
            return
        footer_bits: list[str] = []
        if pdf_config.footer.text:
            footer_bits.append(pdf_config.footer.text)
        if pdf_config.footer.show_printed_at:
            footer_bits.append(generated_at.strftime("Édité le %d/%m/%Y %H:%M"))
        if pdf_config.footer.show_pagination:
            footer_bits.append(f"Page {page_number}")
        if not footer_bits:
            return
        footer_text = " — ".join(footer_bits)
        pdf.setFillColor(theme.muted_text_color)
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        pdf.drawRightString(width - margin_right, margin_bottom - (4 * scale), footer_text)

    def draw_table_header(y_position: float) -> float:
        pdf.setFillColor(theme.table_header_bg)
        pdf.rect(
            margin_left,
            y_position - header_height + (4 * scale),
            table_width,
            header_height,
            stroke=0,
            fill=1,
        )
        pdf.setFillColor(theme.table_header_text)
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        x = margin_left
        for column in columns:
            cell_width = column.ratio * table_width
            if column.align == "center":
                pdf.drawCentredString(x + cell_width / 2, y_position - (6 * scale), column.label)
            else:
                pdf.drawString(x + (4 * scale), y_position - (6 * scale), column.label)
            x += cell_width
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(
            margin_left,
            y_position - header_height + (4 * scale),
            table_width,
            header_height,
            stroke=1,
            fill=0,
        )
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        pdf.setFillColor(theme.text_color)
        return y_position - header_height

    def start_page(page_number: int) -> float:
        apply_theme_reportlab(pdf, page_size, pdf_config.theme, scale=scale)
        draw_watermark(pdf, pdf_config, page_size, scale=scale)
        y_position = draw_header()
        draw_footer(page_number)
        return y_position

    y = start_page(1)
    if truncated_notice:
        pdf.setFillColor(theme.muted_text_color)
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        pdf.drawString(margin_left, y - (4 * scale), truncated_notice)
        y -= line_height
        pdf.setFillColor(theme.text_color)
    y = draw_table_header(y)
    page_number = 1

    def ensure_row_space(required_height: float) -> None:
        nonlocal y, page_number
        if y <= margin_bottom + required_height:
            pdf.showPage()
            page_number += 1
            y = start_page(page_number)
            y = draw_table_header(y)

    row_index = 0
    for row in rows:
        wrapped_values: list[tuple[list[str], float, str]] = []
        max_line_count = 1
        for column in columns:
            cell_width = column.ratio * table_width
            value = str(row.get(column.key, "-")) if row.get(column.key) not in (None, "") else "-"
            lines = _wrap_to_width(
                value,
                cell_width - (8 * scale),
                theme.font_family,
                theme.base_font_size - (1 * scale),
            )
            max_line_count = max(max_line_count, len(lines))
            wrapped_values.append((lines, cell_width, column.align))

        row_height = max_line_count * line_height + row_padding
        ensure_row_space(row_height)

        pdf.setFillColor(theme.table_row_alt_bg if row_index % 2 else theme.background_color)
        pdf.rect(margin_left, y - row_height + 6, table_width, row_height, stroke=0, fill=1)
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(margin_left, y - row_height + (6 * scale), table_width, row_height, stroke=1, fill=0)
        pdf.setFillColor(theme.text_color)

        x = margin_left
        for lines, cell_width, align in wrapped_values:
            text_y = y - (8 * scale)
            for line in lines:
                if align == "center":
                    pdf.drawCentredString(x + cell_width / 2, text_y, line)
                else:
                    pdf.drawString(x + (4 * scale), text_y, line)
                text_y -= line_height
            x += cell_width

        row_index += 1
        y -= row_height

    pdf.save()
    return buffer.getvalue()


def export_stock_inventory_pdf(
    site_key: str,
    user: models.User,
    filters: dict[str, object] | None = None,
) -> bytes:
    filters = filters or {}
    search = str(filters.get("q") or "").strip() or None
    category_id = filters.get("category")
    below_threshold = bool(filters.get("below_threshold"))

    items = services.list_items(search)
    if category_id is not None:
        items = [item for item in items if item.category_id == category_id]
    if below_threshold:
        items = [
            item
            for item in items
            if item.track_low_stock
            and item.low_stock_threshold > 0
            and item.quantity <= item.low_stock_threshold
        ]
    category_map = {category.id: category.name for category in services.list_categories()}

    truncated_notice = None
    if len(items) > MAX_EXPORT_ROWS:
        items = items[:MAX_EXPORT_ROWS]
        truncated_notice = f"Export limité à {MAX_EXPORT_ROWS} lignes."

    columns = [
        InventoryPdfColumn("sku", "SKU", 0.15, "left"),
        InventoryPdfColumn("name", "DÉSIGNATION", 0.30, "left"),
        InventoryPdfColumn("size", "TAILLE", 0.15, "center"),
        InventoryPdfColumn("quantity", "QUANTITÉ", 0.10, "center"),
        InventoryPdfColumn("threshold", "SEUIL", 0.10, "center"),
        InventoryPdfColumn("location", "EMPLACEMENT", 0.20, "left"),
    ]

    rows = []
    for item in items:
        location = item.extra.get("location") if item.extra else None
        if not location and item.extra:
            location = item.extra.get("emplacement")
        if not location and item.category_id:
            location = category_map.get(item.category_id, "-")
        rows.append(
            {
                "sku": item.sku,
                "name": item.name,
                "size": item.size or "-",
                "quantity": item.quantity,
                "threshold": item.low_stock_threshold if item.track_low_stock else "-",
                "location": location or "-",
            }
        )

    site_label = db.SITE_DISPLAY_NAMES.get(site_key.upper(), site_key.upper())
    module_title = pdf_module_label("inventory_habillement")
    return _render_inventory_table_pdf(
        module_key="inventory_habillement",
        module_title=module_title,
        site_label=site_label,
        columns=columns,
        rows=rows,
        truncated_notice=truncated_notice,
    )


def export_pharmacy_inventory_pdf(
    site_key: str,
    user: models.User,
    filters: dict[str, object] | None = None,
) -> bytes:
    filters = filters or {}
    search = str(filters.get("q") or "").strip() or None
    category_id = filters.get("category")
    below_threshold = bool(filters.get("below_threshold"))
    expiring_soon = bool(filters.get("expiring_soon"))

    items = services.list_pharmacy_items()
    if search:
        lowered = search.lower()
        items = [
            item
            for item in items
            if lowered in item.name.lower()
            or lowered in (item.barcode or "").lower()
        ]
    if category_id is not None:
        items = [item for item in items if item.category_id == category_id]
    if below_threshold:
        items = [
            item
            for item in items
            if item.low_stock_threshold > 0 and item.quantity <= item.low_stock_threshold
        ]
    if expiring_soon:
        today = date.today()
        horizon = today + timedelta(days=30)
        filtered: list[models.PharmacyItem] = []
        for item in items:
            expiration = _parse_date(item.expiration_date)
            if expiration is None:
                continue
            if today <= expiration <= horizon:
                filtered.append(item)
        items = filtered

    truncated_notice = None
    if len(items) > MAX_EXPORT_ROWS:
        items = items[:MAX_EXPORT_ROWS]
        truncated_notice = f"Export limité à {MAX_EXPORT_ROWS} lignes."

    columns = [
        InventoryPdfColumn("reference", "RÉFÉRENCE", 0.18, "left"),
        InventoryPdfColumn("name", "NOM", 0.26, "left"),
        InventoryPdfColumn("dosage", "DOSAGE", 0.12, "left"),
        InventoryPdfColumn("packaging", "CONDITIONNEMENT", 0.18, "left"),
        InventoryPdfColumn("quantity", "QUANTITÉ", 0.10, "center"),
        InventoryPdfColumn("threshold", "SEUIL", 0.08, "center"),
        InventoryPdfColumn("expiration", "PÉREMPTION", 0.08, "center"),
    ]

    rows = []
    for item in items:
        rows.append(
            {
                "reference": item.barcode or "-",
                "name": item.name,
                "dosage": item.dosage or "-",
                "packaging": item.packaging or "-",
                "quantity": item.quantity,
                "threshold": item.low_stock_threshold,
                "expiration": _format_date_label(_parse_date(item.expiration_date)),
            }
        )

    site_label = db.SITE_DISPLAY_NAMES.get(site_key.upper(), site_key.upper())
    module_title = pdf_module_label("inventory_pharmacy")
    return _render_inventory_table_pdf(
        module_key="inventory_pharmacy",
        module_title=module_title,
        site_label=site_label,
        columns=columns,
        rows=rows,
        truncated_notice=truncated_notice,
    )

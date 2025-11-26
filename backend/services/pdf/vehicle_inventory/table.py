"""Tabular fallback rendering for vehicle inventory PDFs."""
from __future__ import annotations

from typing import Sequence

from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

from .style import PdfStyleEngine
from .utils import VehicleViewEntry


def _rows_per_page(available_height: float, style_engine: PdfStyleEngine) -> int:
    header_height = style_engine.font("subtitle")[1] + 14
    row_height = style_engine.font("body")[1] + 10
    usable = max(available_height - header_height, row_height)
    return max(1, int(usable // row_height))


def paginate_entries(entries: Sequence[VehicleViewEntry], available_height: float, style_engine: PdfStyleEngine) -> list[list[VehicleViewEntry]]:
    rows = _rows_per_page(available_height, style_engine)
    chunks: list[list[VehicleViewEntry]] = []
    for index in range(0, len(entries), rows):
        chunks.append(list(entries[index : index + rows]))
    return chunks or [[]]


def draw_table(
    canvas,
    *,
    entries: Sequence[VehicleViewEntry],
    bounds: tuple[float, float, float, float],
    style_engine: PdfStyleEngine,
    section_title: str,
) -> None:
    x, y, width, height = bounds
    title_font = style_engine.font("subtitle")
    body_font = style_engine.font("body")

    canvas.saveState()
    canvas.setFillColor(style_engine.color("text"))
    canvas.setFont(*title_font)
    title_y = y + height - title_font[1]
    canvas.drawString(x, title_y, section_title)

    data = [["Nom", "Quantité", "Référence"]]
    for entry in entries:
        data.append([entry.name, str(entry.quantity), entry.reference])

    column_widths = [width * 0.52, width * 0.18, width * 0.30]
    table = Table(data, colWidths=column_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), style_engine.color("table_header")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if style_engine.tokens.name == "premium" else style_engine.color("text")),
                ("FONTNAME", (0, 0), (-1, -1), style_engine.tokens.font_family),
                ("FONTSIZE", (0, 0), (-1, 0), style_engine.font("subtitle")[1]),
                ("FONTSIZE", (0, 1), (-1, -1), body_font[1]),
                ("GRID", (0, 0), (-1, -1), 0.5, style_engine.color("muted")),
                ("BACKGROUND", (0, 1), (-1, -1), style_engine.color("surface")),
                ("TEXTCOLOR", (0, 1), (-1, -1), style_engine.color("text")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEADING", (0, 0), (-1, -1), body_font[1] + 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    table_width, table_height = table.wrap(width, height)
    table_y = title_y - 12 - table_height
    table.drawOn(canvas, x, table_y)
    canvas.restoreState()

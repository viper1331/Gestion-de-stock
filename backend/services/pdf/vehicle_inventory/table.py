"""Table fallback rendering for vehicle inventory PDF."""
from __future__ import annotations

from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle

from .models import VehicleViewEntry
from .style_engine import PdfStyleEngine
from .utils import wrap_text


def paginate_entries(entries: Sequence[VehicleViewEntry], available_height: float, style_engine: PdfStyleEngine) -> list[list[VehicleViewEntry]]:
    rows_per_page = int(max(4, available_height // 40))
    chunks: list[list[VehicleViewEntry]] = []
    for i in range(0, len(entries), rows_per_page):
        chunks.append(list(entries[i : i + rows_per_page]))
    return chunks


def _table_style(style_engine: PdfStyleEngine) -> TableStyle:
    cached = getattr(style_engine, "_table_style", None)
    if cached is not None:
        return cached
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), style_engine.color("surface")),
            ("TEXTCOLOR", (0, 0), (-1, 0), style_engine.color("text")),
            ("FONTNAME", (0, 0), (-1, -1), style_engine.font("body")[0]),
            ("FONTSIZE", (0, 0), (-1, -1), style_engine.font("body")[1]),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.gray),
            ("BACKGROUND", (0, 1), (-1, -1), style_engine.color("background")),
            ("TEXTCOLOR", (0, 1), (-1, -1), style_engine.color("muted")),
        ]
    )
    setattr(style_engine, "_table_style", style)
    return style


def draw_table(canvas, *, entries: Sequence[VehicleViewEntry], bounds: tuple[float, float, float, float], style_engine: PdfStyleEngine, section_title: str) -> None:
    x, y, width, height = bounds
    data = [["Article", "Référence", "Quantité"]]
    for entry in entries:
        data.append([
            "\n".join(wrap_text(entry.name, 32)),
            entry.reference,
            str(entry.quantity),
        ])

    table = Table(data, colWidths=[width * 0.55, width * 0.30, width * 0.15])
    table.setStyle(_table_style(style_engine))
    table.wrapOn(canvas, width, height)
    table.drawOn(canvas, x, y + height - table._height)

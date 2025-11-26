"""Tabular fallback rendering for vehicle inventory PDFs."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

from .style import PdfStyleEngine
from .utils import VehicleViewEntry, layout_dimensions


def render_table(canvas, *, entries: list[VehicleViewEntry], style_engine: PdfStyleEngine):
    """Render a compact table fallback when bubbles cannot be placed."""

    margin_left, margin_top, margin_bottom, margin_right, usable_width, usable_height = layout_dimensions(style_engine)
    data = [["Référence", "Nom", "Quantité", "Détails"]]
    for entry in entries:
        data.append([
            entry.reference_label(),
            entry.display_name(),
            str(entry.total_quantity),
            "\n".join(entry.component_descriptions()) if entry.component_descriptions() else "-",
        ])

    column_widths = [80, 180, 60, 200]
    table = Table(data, colWidths=column_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), style_engine.color("primary")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), style_engine.theme.font_family),
                ("FONTSIZE", (0, 0), (-1, 0), style_engine.font_size("subtitle")),
                ("BACKGROUND", (0, 1), (-1, -1), style_engine.color("surface")),
                ("TEXTCOLOR", (0, 1), (-1, -1), style_engine.color("text")),
                ("GRID", (0, 0), (-1, -1), 0.5, style_engine.color("muted")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    width, height = table.wrapOn(canvas, usable_width, usable_height)
    x = margin_left
    y = canvas._pagesize[1] - margin_top - height - 20
    table.drawOn(canvas, x, y)

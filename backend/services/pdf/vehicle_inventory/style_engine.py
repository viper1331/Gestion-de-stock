"""Centralized styling for vehicle inventory PDF rendering."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


@dataclass
class PdfStyleEngine:
    theme: str = "default"
    logo_path: Path | None = None
    _use_custom_font: bool = False

    def __post_init__(self) -> None:
        self._register_fonts()

    # palettes inspired by Tailwind-like UI
    _palette = {
        "page_background": colors.HexColor("#0A0F18"),
        "background": colors.HexColor("#0D1625"),
        "surface": colors.HexColor("#0F1E36"),
        "overlay": colors.Color(0, 0, 0, alpha=0.0),
        "bubble": colors.HexColor("#0F1E36"),
        "bubble_border": colors.HexColor("#0F1E36"),
        "text": colors.white,
        "muted": colors.HexColor("#D8E2F0"),
        "accent": colors.HexColor("#5EA7FF"),
        "badge_text": colors.white,
        "shadow": colors.Color(0.03, 0.20, 0.39, alpha=0.55),
        "header_band": colors.HexColor("#0D1625"),
        "footer": colors.HexColor("#0D1625"),
        "point_fill": colors.HexColor("#9BC9FF"),
    }

    _premium_palette = {
        **_palette,
        "background": colors.HexColor("#0A0F18"),
        "surface": colors.HexColor("#0D192B"),
        "bubble": colors.HexColor("#0D192B"),
        "bubble_border": colors.HexColor("#1C2C45"),
        "accent": colors.HexColor("#F2B134"),
        "badge_text": colors.black,
        "shadow": colors.Color(0.06, 0.15, 0.32, alpha=0.65),
    }

    def color(self, name: str):
        palette = self._premium_palette if self.theme == "premium" else self._palette
        return palette[name]

    @property
    def margins(self) -> tuple[float, float, float, float]:
        # left, top, bottom, right
        return 22, 22, 22, 22

    def header_height(self) -> float:
        return 40

    def footer_height(self) -> float:
        return 32

    def font(self, role: str) -> Tuple[str, float]:
        base = "Inter" if self._use_custom_font else "Helvetica"
        bold = "Inter-Bold" if self._use_custom_font else "Helvetica-Bold"
        if role == "title":
            return bold, 18
        if role == "subtitle":
            return base, 12
        if role == "body":
            return base, 10
        if role == "small":
            return base, 9
        return base, 9

    def _register_fonts(self) -> None:
        if "Inter" in pdfmetrics.getRegisteredFontNames():
            self._use_custom_font = True
            return
        try:
            pdfmetrics.registerFont(TTFont("Inter", "frontend/public/fonts/Inter-Regular.ttf"))
            pdfmetrics.registerFont(TTFont("Inter-Bold", "frontend/public/fonts/Inter-Bold.ttf"))
            self._use_custom_font = True
        except Exception:
            self._use_custom_font = False

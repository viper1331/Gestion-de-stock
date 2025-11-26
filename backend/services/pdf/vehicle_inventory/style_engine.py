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
        "background": colors.HexColor("#0B1220"),
        "surface": colors.HexColor("#0F172A"),
        "overlay": colors.Color(0, 0, 0, alpha=0.35),
        "bubble": colors.HexColor("#0F172A"),
        "bubble_border": colors.HexColor("#1E293B"),
        "text": colors.white,
        "muted": colors.HexColor("#CBD5E1"),
        "accent": colors.HexColor("#3B82F6"),
        "badge_text": colors.white,
        "shadow": colors.Color(0, 0, 0, alpha=0.35),
        "header_band": colors.HexColor("#0F172A"),
        "footer": colors.HexColor("#1E293B"),
        "point_fill": colors.HexColor("#5EA7FF"),
    }

    _premium_palette = {
        **_palette,
        "background": colors.HexColor("#0b1020"),
        "header_band": colors.HexColor("#0a1329"),
        "surface": colors.HexColor("#0d1b36"),
    }

    def color(self, name: str):
        palette = self._premium_palette if self.theme == "premium" else self._palette
        return palette[name]

    @property
    def margins(self) -> tuple[float, float, float, float]:
        # left, top, bottom, right
        return 30, 20, 24, 30

    def header_height(self) -> float:
        return 48 if self.theme == "premium" else 40

    def footer_height(self) -> float:
        return 32

    def font(self, role: str) -> Tuple[str, float]:
        base = "Inter" if self._use_custom_font else "Helvetica"
        bold = "Inter-Bold" if self._use_custom_font else "Helvetica-Bold"
        if role == "title":
            return bold, 16
        if role == "subtitle":
            return base, 10
        if role == "body":
            return base, 9
        if role == "small":
            return base, 8
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

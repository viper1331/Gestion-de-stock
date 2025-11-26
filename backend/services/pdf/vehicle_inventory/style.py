"""Styling primitives for the vehicle inventory PDF."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    margins: tuple[float, float, float, float]
    fonts: Mapping[str, int]
    colors: Mapping[str, colors.Color]
    header_height: float
    footer_height: float
    font_family: str = "Helvetica"


class PdfStyleEngine:
    """Centralizes color, spacing and typography tokens."""

    _THEMES: dict[str, ThemeTokens] = {
        "default": ThemeTokens(
            name="default",
            margins=(18 * mm, 14 * mm, 16 * mm, 18 * mm),
            fonts={"title": 18, "subtitle": 11, "body": 10, "small": 8},
            colors={
                "background": colors.HexColor("#F8FAFC"),
                "surface": colors.white,
                "bubble": colors.HexColor("#EEF2FF"),
                "bubble_border": colors.HexColor("#CBD5E1"),
                "text": colors.HexColor("#0F172A"),
                "muted": colors.HexColor("#94A3B8"),
                "accent": colors.HexColor("#3B82F6"),
                "badge_text": colors.white,
                "point_fill": colors.white,
                "shadow": colors.Color(0, 0, 0, alpha=0.18),
                "overlay": colors.Color(0, 0, 0, alpha=0.15),
                "header_band": colors.HexColor("#0F172A"),
                "on_header": colors.white,
                "table_header": colors.HexColor("#E2E8F0"),
            },
            header_height=34,
            footer_height=22,
        ),
        "premium": ThemeTokens(
            name="premium",
            margins=(22 * mm, 18 * mm, 18 * mm, 22 * mm),
            fonts={"title": 20, "subtitle": 12, "body": 10, "small": 8},
            colors={
                "background": colors.HexColor("#0B1220"),
                "surface": colors.HexColor("#0F172A"),
                "bubble": colors.HexColor("#0F172A"),
                "bubble_border": colors.HexColor("#1E293B"),
                "text": colors.HexColor("#FFFFFF"),
                "muted": colors.HexColor("#CBD5E1"),
                "accent": colors.HexColor("#3B82F6"),
                "badge_text": colors.white,
                "point_fill": colors.white,
                "shadow": colors.Color(0, 0, 0, alpha=0.3),
                "overlay": colors.Color(0, 0, 0, alpha=0.3),
                "header_band": colors.HexColor("#0F172A"),
                "on_header": colors.HexColor("#F8FAFC"),
                "table_header": colors.HexColor("#1E293B"),
            },
            header_height=46,
            footer_height=28,
            font_family="Helvetica-Bold",
        ),
    }

    def __init__(self, *, theme: str = "default", logo_path: Path | None = None) -> None:
        tokens = self._THEMES.get(theme, self._THEMES["default"])
        self.tokens = tokens
        self.logo_path = logo_path

    @property
    def margins(self) -> tuple[float, float, float, float]:
        return self.tokens.margins

    def color(self, name: str) -> colors.Color:
        return self.tokens.colors.get(name, self.tokens.colors["text"])

    def font(self, name: str, size_override: int | None = None) -> tuple[str, int]:
        size = size_override or self.tokens.fonts.get(name, self.tokens.fonts["body"])
        return self.tokens.font_family, size

    def header_height(self) -> float:
        return self.tokens.header_height

    def footer_height(self) -> float:
        return self.tokens.footer_height

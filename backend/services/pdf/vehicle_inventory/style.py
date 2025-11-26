"""Styling utilities for vehicle inventory PDFs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm


@dataclass(frozen=True)
class PdfStyleTheme:
    """Bundle of design tokens for a PDF theme."""

    name: str
    palette: Mapping[str, Any]
    margins: tuple[float, float, float, float]
    font_family: str
    font_sizes: Mapping[str, int]
    border_radius: float
    shadow: tuple[int, int, int, float]


class PdfStyleEngine:
    """Centralizes visual tokens for vehicle inventory PDFs."""

    _THEMES: dict[str, PdfStyleTheme] = {
        "default": PdfStyleTheme(
            name="default",
            palette={
                "background": colors.whitesmoke,
                "surface": colors.white,
                "primary": colors.HexColor("#0F172A"),
                "secondary": colors.HexColor("#1E293B"),
                "accent": colors.HexColor("#3B82F6"),
                "muted": colors.HexColor("#CBD5E1"),
                "text": colors.HexColor("#0F172A"),
                "text_muted": colors.HexColor("#475569"),
                "bubble": colors.HexColor("#E2E8F0"),
            },
            margins=(15 * mm, 15 * mm, 20 * mm, 15 * mm),
            font_family="Helvetica",
            font_sizes={"title": 16, "subtitle": 12, "body": 10, "small": 8},
            border_radius=4,
            shadow=(1, -1, 3, 0.06),
        ),
        "premium_dark": PdfStyleTheme(
            name="premium_dark",
            palette={
                "background": colors.HexColor("#0F172A"),
                "surface": colors.HexColor("#1E293B"),
                "primary": colors.HexColor("#3B82F6"),
                "secondary": colors.HexColor("#CBD5E1"),
                "accent": colors.HexColor("#3B82F6"),
                "muted": colors.HexColor("#CBD5E1"),
                "text": colors.white,
                "text_muted": colors.HexColor("#CBD5E1"),
                "bubble": colors.HexColor("#1E293B"),
            },
            margins=(18 * mm, 18 * mm, 22 * mm, 18 * mm),
            font_family="Helvetica",
            font_sizes={"title": 18, "subtitle": 13, "body": 11, "small": 9},
            border_radius=6,
            shadow=(2, -2, 6, 0.12),
        ),
        "premium_light": PdfStyleTheme(
            name="premium_light",
            palette={
                "background": colors.HexColor("#FFFFFF"),
                "surface": colors.HexColor("#F8FAFC"),
                "primary": colors.HexColor("#3B82F6"),
                "secondary": colors.HexColor("#0F172A"),
                "accent": colors.HexColor("#1E293B"),
                "muted": colors.HexColor("#CBD5E1"),
                "text": colors.HexColor("#0F172A"),
                "text_muted": colors.HexColor("#475569"),
                "bubble": colors.HexColor("#E2E8F0"),
            },
            margins=(18 * mm, 18 * mm, 22 * mm, 18 * mm),
            font_family="Helvetica",
            font_sizes={"title": 18, "subtitle": 13, "body": 11, "small": 9},
            border_radius=6,
            shadow=(1, -1, 5, 0.1),
        ),
    }

    def __init__(self, *, theme: str = "default") -> None:
        if theme not in self._THEMES:
            theme = "default"
        self.theme = self._THEMES[theme]

    @property
    def margins(self) -> tuple[float, float, float, float]:
        return self.theme.margins

    def font_size(self, role: str) -> int:
        return self.theme.font_sizes.get(role, self.theme.font_sizes["body"])

    def color(self, role: str):
        return self.theme.palette.get(role, self.theme.palette["text"])

    @property
    def border_radius(self) -> float:
        return self.theme.border_radius

    @property
    def shadow(self) -> tuple[int, int, int, float]:
        return self.theme.shadow

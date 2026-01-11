"""ReportLab theme helpers."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Tuple

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from backend.core.pdf_config_models import PdfThemeConfig
from backend.core.pdf_theme import parse_color

_BUILTIN_FONTS = {"Helvetica", "Times-Roman", "Courier"}


@dataclass(frozen=True)
class ResolvedReportlabTheme:
    font_family: str
    base_font_size: int
    heading_font_size: int
    text_color: colors.Color
    muted_text_color: colors.Color
    accent_color: colors.Color
    table_header_bg: colors.Color
    table_header_text: colors.Color
    table_row_alt_bg: colors.Color
    border_color: colors.Color
    background_color: colors.Color
    background_alpha: float


def _font_assets_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "pdf" / "fonts"


def _iter_font_files() -> Iterable[Path]:
    fonts_dir = _font_assets_dir()
    if not fonts_dir.exists():
        return []
    return list(fonts_dir.glob("*.ttf"))


def _register_font_file(path: Path) -> str | None:
    font_name = path.stem
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    try:
        pdfmetrics.registerFont(TTFont(font_name, str(path)))
    except Exception:
        return None
    return font_name


def _register_font_assets() -> list[str]:
    registered: list[str] = []
    for path in _iter_font_files():
        name = _register_font_file(path)
        if name:
            registered.append(name)
    return registered


@lru_cache(maxsize=1)
def supported_fonts() -> list[str]:
    _register_font_assets()
    fonts = set(pdfmetrics.getRegisteredFontNames()) | _BUILTIN_FONTS
    return sorted(fonts)


def resolve_reportlab_theme(theme: PdfThemeConfig) -> ResolvedReportlabTheme:
    theme_key = tuple(sorted(theme.model_dump().items()))
    return _resolve_reportlab_theme_cached(theme_key)


def scale_reportlab_theme(theme: ResolvedReportlabTheme, scale: float) -> ResolvedReportlabTheme:
    if scale == 1.0:
        return theme
    return ResolvedReportlabTheme(
        font_family=theme.font_family,
        base_font_size=theme.base_font_size * scale,
        heading_font_size=theme.heading_font_size * scale,
        text_color=theme.text_color,
        muted_text_color=theme.muted_text_color,
        accent_color=theme.accent_color,
        table_header_bg=theme.table_header_bg,
        table_header_text=theme.table_header_text,
        table_row_alt_bg=theme.table_row_alt_bg,
        border_color=theme.border_color,
        background_color=theme.background_color,
        background_alpha=theme.background_alpha,
    )


@lru_cache(maxsize=32)
def _resolve_reportlab_theme_cached(theme_key: tuple[tuple[str, object], ...]) -> ResolvedReportlabTheme:
    theme = PdfThemeConfig(**dict(theme_key))
    default_theme = PdfThemeConfig()

    def _safe_color(value: str, fallback: str) -> Tuple[colors.Color, float]:
        try:
            r, g, b, a = parse_color(value)
        except ValueError:
            r, g, b, a = parse_color(fallback)
        return colors.Color(r, g, b), a

    text_color, _ = _safe_color(theme.text_color, default_theme.text_color)
    muted_text_color, _ = _safe_color(theme.muted_text_color, default_theme.muted_text_color)
    accent_color, _ = _safe_color(theme.accent_color, default_theme.accent_color)
    table_header_bg, _ = _safe_color(theme.table_header_bg, default_theme.table_header_bg)
    table_header_text, _ = _safe_color(theme.table_header_text, default_theme.table_header_text)
    table_row_alt_bg, _ = _safe_color(theme.table_row_alt_bg, default_theme.table_row_alt_bg)
    border_color, _ = _safe_color(theme.border_color, default_theme.border_color)
    background_color, background_alpha = _safe_color(
        theme.background_color, default_theme.background_color
    )

    font_family = theme.font_family
    available_fonts = set(pdfmetrics.getRegisteredFontNames()) | _BUILTIN_FONTS
    if font_family not in available_fonts:
        _register_font_assets()
        available_fonts = set(pdfmetrics.getRegisteredFontNames()) | _BUILTIN_FONTS
    if font_family not in available_fonts:
        font_family = default_theme.font_family

    return ResolvedReportlabTheme(
        font_family=font_family,
        base_font_size=theme.base_font_size,
        heading_font_size=theme.heading_font_size,
        text_color=text_color,
        muted_text_color=muted_text_color,
        accent_color=accent_color,
        table_header_bg=table_header_bg,
        table_header_text=table_header_text,
        table_row_alt_bg=table_row_alt_bg,
        border_color=border_color,
        background_color=background_color,
        background_alpha=background_alpha,
    )


def _position_offset(
    container: float, content: float, *, align: str, is_horizontal: bool
) -> float:
    align = align.lower()
    if is_horizontal:
        if "left" in align:
            return 0
        if "right" in align:
            return container - content
    else:
        if "top" in align:
            return container - content
        if "bottom" in align:
            return 0
    return (container - content) / 2


def _draw_background_image(
    pdf_canvas: Any, page_size: tuple[float, float], theme: PdfThemeConfig
) -> None:
    if not theme.background_image:
        return
    try:
        if theme.background_image.startswith(("http://", "https://")):
            image = ImageReader(theme.background_image)
        else:
            image_path = Path(theme.background_image)
            if not image_path.exists():
                return
            image = ImageReader(str(image_path))
    except Exception:
        return
    width, height = page_size
    img_width, img_height = image.getSize()
    if img_width <= 0 or img_height <= 0:
        return
    if theme.background_fit == "contain":
        scale = min(width / img_width, height / img_height)
    else:
        scale = max(width / img_width, height / img_height)
    draw_width = img_width * scale
    draw_height = img_height * scale
    offset_x = _position_offset(width, draw_width, align=theme.background_position, is_horizontal=True)
    offset_y = _position_offset(height, draw_height, align=theme.background_position, is_horizontal=False)
    pdf_canvas.saveState()
    try:
        pdf_canvas.setFillAlpha(theme.background_opacity)
    except AttributeError:
        pass
    pdf_canvas.drawImage(image, offset_x, offset_y, width=draw_width, height=draw_height, mask="auto")
    pdf_canvas.restoreState()


def apply_theme_reportlab(
    pdf_canvas: Any, doc: Any, theme: PdfThemeConfig, *, scale: float = 1.0
) -> ResolvedReportlabTheme:
    page_size = doc.pagesize if hasattr(doc, "pagesize") else doc
    width, height = page_size
    resolved = resolve_reportlab_theme(theme)
    resolved = scale_reportlab_theme(resolved, scale)

    if theme.background_mode == "color":
        pdf_canvas.saveState()
        try:
            pdf_canvas.setFillAlpha(theme.background_opacity)
        except AttributeError:
            pass
        pdf_canvas.setFillColor(resolved.background_color)
        pdf_canvas.rect(0, 0, width, height, stroke=0, fill=1)
        pdf_canvas.restoreState()
    elif theme.background_mode == "image":
        _draw_background_image(pdf_canvas, page_size, theme)

    pdf_canvas.setFont(resolved.font_family, resolved.base_font_size)
    pdf_canvas.setFillColor(resolved.text_color)
    return resolved


def theme_meta() -> dict[str, object]:
    return {
        "supported_fonts": supported_fonts(),
        "accepted_color_formats": ["#RGB", "#RRGGBB", "#RRGGBBAA", "rgb(r,g,b)", "rgba(r,g,b,a)", "transparent"],
        "renderer_compatibility": {
            "reportlab": {
                "background_image": True,
                "alpha": False,
                "notes": ["L'alpha peut être ignoré selon la version de ReportLab."],
            },
            "html": {
                "background_image": True,
                "alpha": True,
                "notes": [],
            },
        },
    }

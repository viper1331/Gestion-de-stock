"""Pydantic models for PDF export configuration."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.pdf_theme import parse_color


class PdfMargins(BaseModel):
    top_mm: float = 12
    right_mm: float = 12
    bottom_mm: float = 12
    left_mm: float = 12


class PdfFormatConfig(BaseModel):
    size: Literal["A3", "A4", "A5", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margin_preset: Literal["normal", "narrow", "wide", "custom"] = "normal"
    margins: PdfMargins = Field(default_factory=PdfMargins)
    density: Literal["comfort", "standard", "compact"] = "standard"


class PdfBrandingConfig(BaseModel):
    logo_enabled: bool = True
    logo_url: str | None = None
    logo_path: str | None = None
    logo_width_mm: float = 24
    logo_position: Literal["left", "center", "right"] = "left"
    company_name: str | None = None
    accent_color: str | None = "#4f46e5"


class PdfHeaderConfig(BaseModel):
    enabled: bool = True
    title_template: str = "{module_title}"
    subtitle_template: str = "{generated_at}"
    info_keys: list[str] = Field(default_factory=list)


class PdfColumnConfig(BaseModel):
    key: str
    label: str
    visible: bool = True


class PdfContentConfig(BaseModel):
    columns: list[PdfColumnConfig] = Field(default_factory=list)
    sort_by: str | None = None
    group_by: str | None = None
    show_totals: bool = False


class PdfGroupingConfig(BaseModel):
    enabled: bool = False
    keys: list[str] = Field(default_factory=list)
    header_style: Literal["bar", "inline", "none"] = "bar"
    show_counts: bool = False
    counts_scope: Literal["level", "leaf"] = "level"
    show_subtotals: bool = False
    subtotal_columns: list[str] = Field(default_factory=list)
    subtotal_scope: Literal["level", "leaf"] = "level"
    page_break_between_level1: bool = False


class PdfFooterConfig(BaseModel):
    enabled: bool = True
    show_pagination: bool = True
    show_printed_at: bool = True
    text: str | None = None


class PdfWatermarkConfig(BaseModel):
    enabled: bool = False
    text: str = "CONFIDENTIEL"
    opacity: float = 0.08


class PdfFilenameConfig(BaseModel):
    pattern: str = "{module}_{date:%Y%m%d_%H%M}.pdf"


class PdfAdvancedConfig(BaseModel):
    font_family: str = "Helvetica"
    base_font_size: int = 10
    header_bg_color: str = "#111827"
    header_text_color: str = "#f8fafc"
    table_header_bg_color: str = "#1f2937"
    table_header_text_color: str = "#f8fafc"
    row_alt_bg_color: str = "#0f172a"
    barcode_title_font_size: int = 10
    barcode_label_font_size: int = 9
    barcode_meta_font_size: int = 8


class PdfThemeConfig(BaseModel):
    font_family: str = "Helvetica"
    base_font_size: int = 10
    heading_font_size: int = 14
    text_color: str = "#111827"
    muted_text_color: str = "#64748b"
    accent_color: str = "#4f46e5"
    table_header_bg: str = "#1f2937"
    table_header_text: str = "#f8fafc"
    table_row_alt_bg: str = "#f1f5f9"
    border_color: str = "#e2e8f0"
    background_mode: Literal["none", "color", "image"] = "none"
    background_color: str = "#ffffff"
    background_image: str | None = None
    background_opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    background_fit: Literal["cover", "contain"] = "cover"
    background_position: str = "center"

    @field_validator(
        "text_color",
        "muted_text_color",
        "accent_color",
        "table_header_bg",
        "table_header_text",
        "table_row_alt_bg",
        "border_color",
        "background_color",
    )
    @classmethod
    def validate_colors(cls, value: str) -> str:
        try:
            parse_color(value)
        except ValueError as exc:
            raise ValueError(
                f"Couleur invalide '{value}'. Formats acceptés: #RGB, #RRGGBB, #RRGGBBAA, rgb(), rgba(), transparent."
            ) from exc
        return value


class PdfConfig(BaseModel):
    format: PdfFormatConfig = Field(default_factory=PdfFormatConfig)
    branding: PdfBrandingConfig = Field(default_factory=PdfBrandingConfig)
    header: PdfHeaderConfig = Field(default_factory=PdfHeaderConfig)
    content: PdfContentConfig = Field(default_factory=PdfContentConfig)
    grouping: PdfGroupingConfig = Field(default_factory=PdfGroupingConfig)
    footer: PdfFooterConfig = Field(default_factory=PdfFooterConfig)
    watermark: PdfWatermarkConfig = Field(default_factory=PdfWatermarkConfig)
    filename: PdfFilenameConfig = Field(default_factory=PdfFilenameConfig)
    advanced: PdfAdvancedConfig = Field(default_factory=PdfAdvancedConfig)
    theme: PdfThemeConfig = Field(default_factory=PdfThemeConfig)


class PdfConfigOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: PdfFormatConfig | None = None
    branding: PdfBrandingConfig | None = None
    header: PdfHeaderConfig | None = None
    content: PdfContentConfig | None = None
    grouping: PdfGroupingConfig | None = None
    footer: PdfFooterConfig | None = None
    watermark: PdfWatermarkConfig | None = None
    filename: PdfFilenameConfig | None = None
    advanced: PdfAdvancedConfig | None = None
    theme: PdfThemeConfig | None = None


class PdfModuleConfig(BaseModel):
    override_global: bool = False
    config: PdfConfig | PdfConfigOverrides = Field(default_factory=PdfConfigOverrides)


class PdfPresetConfig(BaseModel):
    name: str
    config: PdfConfig


class PdfColumnMeta(BaseModel):
    key: str
    label: str
    is_numeric: bool = False
    default_visible: bool = True
    column_type: Literal["string", "number", "date"] = "string"


class PdfGroupableColumnMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    label: str
    is_numeric: bool = Field(default=False, alias="isNumeric")
    is_visible_by_default: bool = Field(default=True, alias="isVisibleByDefault")
    column_type: Literal["string", "number", "date"] = Field(default="string", alias="type")


class PdfModuleGroupingMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grouping_supported: bool = Field(default=False, alias="groupingSupported")
    groupable_columns: list[PdfGroupableColumnMeta] = Field(
        default_factory=list,
        alias="groupableColumns",
    )


class PdfModuleMeta(BaseModel):
    key: str
    label: str
    variables: list[str] = Field(default_factory=list)
    columns: list[PdfColumnMeta] = Field(default_factory=list)
    sort_options: list[str] = Field(default_factory=list)
    group_options: list[str] = Field(default_factory=list)
    renderers: list[Literal["html", "reportlab"]] = Field(default_factory=list)
    grouping_supported: bool = True


class PdfExportConfig(BaseModel):
    global_config: PdfConfig = Field(default_factory=PdfConfig)
    modules: dict[str, PdfModuleConfig] = Field(default_factory=dict)
    presets: dict[str, PdfPresetConfig] = Field(default_factory=dict)
    module_meta: dict[str, PdfModuleMeta] = Field(default_factory=dict)


class PdfConfigMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    supported_fonts: list[str] = Field(default_factory=list)
    accepted_color_formats: list[str] = Field(default_factory=list)
    renderer_compatibility: dict[str, dict[str, object]] = Field(default_factory=dict)
    groupable_columns: list[PdfGroupableColumnMeta] = Field(
        default_factory=list,
        alias="groupableColumns",
    )
    module_grouping: dict[str, PdfModuleGroupingMeta] = Field(
        default_factory=dict,
        alias="moduleGrouping",
    )

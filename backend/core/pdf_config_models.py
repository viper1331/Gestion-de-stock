"""Pydantic models for PDF export configuration."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PdfMargins(BaseModel):
    top_mm: float = 12
    right_mm: float = 12
    bottom_mm: float = 12
    left_mm: float = 12


class PdfFormatConfig(BaseModel):
    size: Literal["A4", "A5", "Letter"] = "A4"
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


class PdfConfig(BaseModel):
    format: PdfFormatConfig = Field(default_factory=PdfFormatConfig)
    branding: PdfBrandingConfig = Field(default_factory=PdfBrandingConfig)
    header: PdfHeaderConfig = Field(default_factory=PdfHeaderConfig)
    content: PdfContentConfig = Field(default_factory=PdfContentConfig)
    footer: PdfFooterConfig = Field(default_factory=PdfFooterConfig)
    watermark: PdfWatermarkConfig = Field(default_factory=PdfWatermarkConfig)
    filename: PdfFilenameConfig = Field(default_factory=PdfFilenameConfig)
    advanced: PdfAdvancedConfig = Field(default_factory=PdfAdvancedConfig)


class PdfConfigOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: PdfFormatConfig | None = None
    branding: PdfBrandingConfig | None = None
    header: PdfHeaderConfig | None = None
    content: PdfContentConfig | None = None
    footer: PdfFooterConfig | None = None
    watermark: PdfWatermarkConfig | None = None
    filename: PdfFilenameConfig | None = None
    advanced: PdfAdvancedConfig | None = None


class PdfModuleConfig(BaseModel):
    override_global: bool = False
    config: PdfConfig | PdfConfigOverrides = Field(default_factory=PdfConfigOverrides)


class PdfPresetConfig(BaseModel):
    name: str
    config: PdfConfig


class PdfColumnMeta(BaseModel):
    key: str
    label: str
    default_visible: bool = True


class PdfModuleMeta(BaseModel):
    key: str
    label: str
    variables: list[str] = Field(default_factory=list)
    columns: list[PdfColumnMeta] = Field(default_factory=list)
    sort_options: list[str] = Field(default_factory=list)
    group_options: list[str] = Field(default_factory=list)
    renderers: list[Literal["html", "reportlab"]] = Field(default_factory=list)


class PdfExportConfig(BaseModel):
    global_config: PdfConfig = Field(default_factory=PdfConfig)
    modules: dict[str, PdfModuleConfig] = Field(default_factory=dict)
    presets: dict[str, PdfPresetConfig] = Field(default_factory=dict)
    module_meta: dict[str, PdfModuleMeta] = Field(default_factory=dict)

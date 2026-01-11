"""PDF export configuration service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5, letter, landscape, portrait
from reportlab.lib.units import mm

from backend.core.pdf_config_models import (
    PdfAdvancedConfig,
    PdfBrandingConfig,
    PdfColumnConfig,
    PdfColumnMeta,
    PdfGroupableColumnMeta,
    PdfConfig,
    PdfConfigOverrides,
    PdfContentConfig,
    PdfExportConfig,
    PdfFilenameConfig,
    PdfFooterConfig,
    PdfFormatConfig,
    PdfHeaderConfig,
    PdfMargins,
    PdfModuleConfig,
    PdfModuleMeta,
    PdfPresetConfig,
    PdfThemeConfig,
    PdfWatermarkConfig,
)
from backend.core.system_config import get_config, save_config
from backend.services.pdf.theme import apply_theme_reportlab, resolve_reportlab_theme, theme_meta


@dataclass(frozen=True)
class PdfResolvedConfig:
    module_key: str
    module_label: str
    config: PdfConfig
    variables: list[str]
    renderers: list[str]


def _default_format() -> PdfFormatConfig:
    return PdfFormatConfig(
        size="A4",
        orientation="portrait",
        margin_preset="normal",
        margins=PdfMargins(top_mm=15, right_mm=15, bottom_mm=15, left_mm=15),
        density="standard",
    )


def _default_branding() -> PdfBrandingConfig:
    return PdfBrandingConfig(
        logo_enabled=True,
        logo_url=None,
        logo_path=None,
        logo_width_mm=24,
        logo_position="left",
        company_name="Gestion Stock Pro",
        accent_color="#4f46e5",
    )


def _default_header() -> PdfHeaderConfig:
    return PdfHeaderConfig(
        enabled=True,
        title_template="{module_title}",
        subtitle_template="Généré le {generated_at}",
        info_keys=[],
    )


def _default_content() -> PdfContentConfig:
    return PdfContentConfig(columns=[], sort_by=None, group_by=None, show_totals=False)


def _default_footer() -> PdfFooterConfig:
    return PdfFooterConfig(
        enabled=True,
        show_pagination=True,
        show_printed_at=True,
        text=None,
    )


def _default_watermark() -> PdfWatermarkConfig:
    return PdfWatermarkConfig(enabled=False, text="CONFIDENTIEL", opacity=0.08)


def _default_filename() -> PdfFilenameConfig:
    return PdfFilenameConfig(pattern="{module}_{date:%Y%m%d_%H%M}.pdf")


def _default_advanced() -> PdfAdvancedConfig:
    return PdfAdvancedConfig(
        font_family="Helvetica",
        base_font_size=10,
        header_bg_color="#111827",
        header_text_color="#f8fafc",
        table_header_bg_color="#1f2937",
        table_header_text_color="#f8fafc",
        row_alt_bg_color="#0f172a",
    )


def _default_theme() -> PdfThemeConfig:
    return PdfThemeConfig(
        font_family="Helvetica",
        base_font_size=10,
        heading_font_size=14,
        text_color="#111827",
        muted_text_color="#64748b",
        accent_color="#4f46e5",
        table_header_bg="#1f2937",
        table_header_text="#f8fafc",
        table_row_alt_bg="#f1f5f9",
        border_color="#e2e8f0",
        background_mode="none",
        background_color="#ffffff",
        background_image=None,
        background_opacity=1.0,
        background_fit="cover",
        background_position="center",
    )


def _default_config() -> PdfConfig:
    return PdfConfig(
        format=_default_format(),
        branding=_default_branding(),
        header=_default_header(),
        content=_default_content(),
        footer=_default_footer(),
        watermark=_default_watermark(),
        filename=_default_filename(),
        advanced=_default_advanced(),
        theme=_default_theme(),
    )


def _build_presets() -> dict[str, PdfPresetConfig]:
    base = _default_config()
    presets: dict[str, PdfPresetConfig] = {
        "Entreprise": PdfPresetConfig(name="Entreprise", config=base.model_copy(deep=True)),
        "Compact": PdfPresetConfig(
            name="Compact",
            config=base.model_copy(
                update={
                    "format": PdfFormatConfig(
                        size="A4",
                        orientation="portrait",
                        margin_preset="narrow",
                        margins=PdfMargins(top_mm=10, right_mm=10, bottom_mm=10, left_mm=10),
                        density="compact",
                    ),
                    "theme": PdfThemeConfig(
                        font_family="Helvetica",
                        base_font_size=9,
                        heading_font_size=12,
                        text_color="#0f172a",
                        muted_text_color="#475569",
                        accent_color="#6366f1",
                        table_header_bg="#111827",
                        table_header_text="#e2e8f0",
                        table_row_alt_bg="#f8fafc",
                        border_color="#e2e8f0",
                        background_mode="none",
                        background_color="#ffffff",
                        background_opacity=1.0,
                        background_fit="cover",
                        background_position="center",
                    ),
                }
            ),
        ),
        "Audit": PdfPresetConfig(
            name="Audit",
            config=base.model_copy(
                update={
                    "watermark": PdfWatermarkConfig(enabled=True, text="AUDIT", opacity=0.12),
                    "footer": PdfFooterConfig(
                        enabled=True,
                        show_pagination=True,
                        show_printed_at=True,
                        text="Document réservé à l'audit interne.",
                    ),
                    "theme": PdfThemeConfig(
                        font_family="Helvetica",
                        base_font_size=10,
                        heading_font_size=14,
                        text_color="#111827",
                        muted_text_color="#4b5563",
                        accent_color="#0ea5e9",
                        table_header_bg="#0f172a",
                        table_header_text="#f8fafc",
                        table_row_alt_bg="#e2e8f0",
                        border_color="#cbd5f5",
                        background_mode="none",
                        background_color="#ffffff",
                        background_opacity=1.0,
                        background_fit="cover",
                        background_position="center",
                    ),
                }
            ),
        ),
        "Client": PdfPresetConfig(
            name="Client",
            config=base.model_copy(
                update={
                    "header": PdfHeaderConfig(
                        enabled=True,
                        title_template="{module_title}",
                        subtitle_template="Document client",
                        info_keys=[],
                    ),
                    "footer": PdfFooterConfig(
                        enabled=True,
                        show_pagination=True,
                        show_printed_at=False,
                        text="Merci de votre confiance.",
                    ),
                    "theme": PdfThemeConfig(
                        font_family="Helvetica",
                        base_font_size=10,
                        heading_font_size=14,
                        text_color="#0f172a",
                        muted_text_color="#64748b",
                        accent_color="#14b8a6",
                        table_header_bg="#0f172a",
                        table_header_text="#f8fafc",
                        table_row_alt_bg="#f1f5f9",
                        border_color="#e2e8f0",
                        background_mode="none",
                        background_color="#ffffff",
                        background_opacity=1.0,
                        background_fit="cover",
                        background_position="center",
                    ),
                }
            ),
        ),
        "Sans en-tête": PdfPresetConfig(
            name="Sans en-tête",
            config=base.model_copy(update={"header": PdfHeaderConfig(enabled=False)}),
        ),
    }
    return presets


def _build_module_meta() -> dict[str, PdfModuleMeta]:
    return {
        "vehicle_inventory": PdfModuleMeta(
            key="vehicle_inventory",
            label="Inventaire véhicules",
            variables=["module", "module_title", "date", "generated_at", "vehicle"],
            columns=[
                PdfColumnMeta(key="name", label="Matériel", default_visible=True),
                PdfColumnMeta(key="quantity", label="Quantité", default_visible=True, is_numeric=True),
                PdfColumnMeta(key="size", label="Taille / Variante", default_visible=True),
                PdfColumnMeta(key="category", label="Catégorie", default_visible=True),
                PdfColumnMeta(key="lots", label="Lot(s)", default_visible=True),
                PdfColumnMeta(key="expiration", label="Péremption", default_visible=True),
                PdfColumnMeta(key="threshold", label="Seuil", default_visible=True, is_numeric=True),
            ],
            sort_options=["nom", "catégorie", "emplacement"],
            group_options=["catégorie", "emplacement"],
            renderers=["html", "reportlab"],
        ),
        "remise_inventory": PdfModuleMeta(
            key="remise_inventory",
            label="Inventaire remises",
            variables=["module", "module_title", "date", "generated_at"],
            columns=[
                PdfColumnMeta(key="name", label="Matériel", default_visible=True),
                PdfColumnMeta(key="quantity", label="Quantité", default_visible=True, is_numeric=True),
                PdfColumnMeta(key="size", label="Taille / Variante", default_visible=True),
                PdfColumnMeta(key="category", label="Catégorie", default_visible=True),
                PdfColumnMeta(key="lots", label="Lot(s)", default_visible=True),
                PdfColumnMeta(key="expiration", label="Péremption", default_visible=True),
                PdfColumnMeta(key="threshold", label="Seuil", default_visible=True, is_numeric=True),
            ],
            sort_options=["nom", "catégorie", "emplacement"],
            group_options=["catégorie"],
            renderers=["reportlab"],
        ),
        "purchase_orders": PdfModuleMeta(
            key="purchase_orders",
            label="Bons de commande",
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True),
                PdfColumnMeta(key="ordered", label="Commandé", default_visible=True, is_numeric=True),
                PdfColumnMeta(key="received", label="Réceptionné", default_visible=True, is_numeric=True),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "remise_orders": PdfModuleMeta(
            key="remise_orders",
            label="Bons de commande remises",
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True),
                PdfColumnMeta(key="ordered", label="Commandé", default_visible=True, is_numeric=True),
                PdfColumnMeta(key="received", label="Réceptionné", default_visible=True, is_numeric=True),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "pharmacy_orders": PdfModuleMeta(
            key="pharmacy_orders",
            label="Bons de commande pharmacie",
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True),
                PdfColumnMeta(key="ordered", label="Commandé", default_visible=True, is_numeric=True),
                PdfColumnMeta(key="received", label="Réceptionné", default_visible=True, is_numeric=True),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "barcode": PdfModuleMeta(
            key="barcode",
            label="Codes-barres",
            variables=["module", "module_title", "date", "generated_at"],
            columns=[
                PdfColumnMeta(key="barcode", label="Code-barres", default_visible=True),
            ],
            sort_options=[],
            group_options=[],
            renderers=["reportlab"],
        ),
    }


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in updates.items():
        if value is None and isinstance(merged.get(key), dict):
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_config_data(raw: dict[str, Any] | None, defaults: PdfConfig) -> dict[str, Any]:
    return _deep_merge(defaults.model_dump(), raw or {})


def _normalize_export_config_data(raw: dict[str, Any], defaults: PdfExportConfig) -> dict[str, Any]:
    data = dict(raw)
    global_config = _normalize_config_data(data.get("global_config"), defaults.global_config)
    presets: dict[str, Any] = {}
    for name, preset in (data.get("presets") or {}).items():
        preset_data = dict(preset or {})
        preset_data["config"] = _normalize_config_data(preset_data.get("config"), defaults.global_config)
        presets[name] = preset_data
    modules: dict[str, Any] = {}
    for key, module in (data.get("modules") or {}).items():
        module_data = dict(module or {})
        override_global = bool(module_data.get("override_global"))
        module_config = module_data.get("config")
        if override_global:
            module_data["config"] = _deep_merge(global_config, module_config or {})
        else:
            module_data["config"] = module_config or {}
        modules[key] = module_data
    data["global_config"] = global_config
    data["presets"] = presets
    data["modules"] = modules
    return data


def _apply_overrides(base: PdfConfig, overrides: PdfConfigOverrides) -> PdfConfig:
    base_data = base.model_dump()
    override_data = overrides.model_dump(exclude_none=True)
    return PdfConfig.model_validate(_deep_merge(base_data, override_data))


def _diff_config(reference: PdfConfig, candidate: PdfConfig) -> PdfConfigOverrides:
    diff: dict[str, Any] = {}
    ref_data = reference.model_dump()
    cand_data = candidate.model_dump()
    for key, value in cand_data.items():
        if value != ref_data.get(key):
            diff[key] = value
    return PdfConfigOverrides.model_validate(diff)


def get_module_meta() -> dict[str, PdfModuleMeta]:
    return _build_module_meta()


def get_pdf_config_meta() -> dict[str, object]:
    meta = theme_meta()
    groupable_columns: list[PdfGroupableColumnMeta] = []
    seen_keys: set[str] = set()
    for module in get_module_meta().values():
        for column in module.columns:
            if column.key in seen_keys:
                continue
            seen_keys.add(column.key)
            groupable_columns.append(
                PdfGroupableColumnMeta(
                    key=column.key,
                    label=column.label,
                    is_numeric=column.is_numeric,
                    is_visible_by_default=column.default_visible,
                )
            )
    meta["groupableColumns"] = groupable_columns
    return meta


def _ensure_module_columns(module_key: str, config: PdfConfig) -> PdfConfig:
    meta = get_module_meta().get(module_key)
    if not meta:
        return config
    if config.content.columns:
        return config
    config = config.model_copy(deep=True)
    config.content.columns = [
        PdfColumnConfig(key=col.key, label=col.label, visible=col.default_visible)
        for col in meta.columns
    ]
    return config


def _build_default_export_config() -> PdfExportConfig:
    return PdfExportConfig(
        global_config=_default_config(),
        modules={},
        presets=_build_presets(),
        module_meta=get_module_meta(),
    )


def get_pdf_export_config() -> PdfExportConfig:
    system_config = get_config()
    stored = system_config.pdf_exports
    defaults = _build_default_export_config()
    if stored is None:
        return defaults
    if isinstance(stored, PdfExportConfig):
        config = stored
    else:
        normalized = _normalize_export_config_data(stored, defaults)
        config = PdfExportConfig.model_validate(normalized)

    merged_presets = defaults.presets | config.presets
    module_meta = get_module_meta()
    return config.model_copy(
        update={
            "presets": merged_presets,
            "module_meta": module_meta,
        }
    )


def save_pdf_export_config(payload: PdfExportConfig) -> PdfExportConfig:
    defaults = _build_default_export_config()
    global_config = payload.global_config or defaults.global_config
    module_overrides: dict[str, PdfModuleConfig] = {}

    for key, module_cfg in payload.modules.items():
        if not module_cfg.override_global:
            if module_cfg.config:
                module_overrides[key] = PdfModuleConfig(override_global=False, config=PdfConfigOverrides())
            continue

        if isinstance(module_cfg.config, PdfConfig):
            full_config = module_cfg.config
        else:
            full_config = _apply_overrides(global_config, module_cfg.config)
        overrides = _diff_config(global_config, full_config)
        if overrides.model_dump(exclude_none=True):
            module_overrides[key] = PdfModuleConfig(override_global=True, config=overrides)
        else:
            module_overrides[key] = PdfModuleConfig(override_global=True, config=PdfConfigOverrides())

    prepared = PdfExportConfig(
        global_config=global_config,
        modules=module_overrides,
        presets=payload.presets or defaults.presets,
        module_meta={},
    )
    system_config = get_config()
    system_config.pdf_exports = prepared
    save_config(system_config)
    return get_pdf_export_config()


def resolve_pdf_config(module_name: str, preset_name: str | None = None, config: PdfExportConfig | None = None) -> PdfResolvedConfig:
    export_config = config or get_pdf_export_config()
    meta = export_config.module_meta.get(module_name) or get_module_meta().get(module_name)
    if not meta:
        meta = PdfModuleMeta(key=module_name, label=module_name, renderers=["reportlab"])
    resolved = export_config.global_config.model_copy(deep=True)

    preset = export_config.presets.get(preset_name) if preset_name else None
    if preset:
        resolved = preset.config.model_copy(deep=True)

    module_cfg = export_config.modules.get(module_name)
    if module_cfg and module_cfg.override_global:
        overrides = module_cfg.config
        if isinstance(overrides, PdfConfig):
            resolved = overrides.model_copy(deep=True)
        else:
            resolved = _apply_overrides(resolved, overrides)

    resolved = _ensure_module_columns(module_name, resolved)
    return PdfResolvedConfig(
        module_key=module_name,
        module_label=meta.label,
        config=resolved,
        variables=meta.variables,
        renderers=meta.renderers,
    )


def page_size_for_format(format_config: PdfFormatConfig) -> tuple[float, float]:
    size_map = {"A4": A4, "A5": A5, "Letter": letter}
    base = size_map.get(format_config.size, A4)
    if format_config.orientation == "landscape":
        return landscape(base)
    return portrait(base)


def margins_for_format(format_config: PdfFormatConfig) -> tuple[float, float, float, float]:
    margins = format_config.margins
    return (
        margins.top_mm * mm,
        margins.right_mm * mm,
        margins.bottom_mm * mm,
        margins.left_mm * mm,
    )


def resolve_color(hex_value: str | None, fallback: colors.Color) -> colors.Color:
    if not hex_value:
        return fallback
    value = hex_value.lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        r = int(value[0:2], 16) / 255
        g = int(value[2:4], 16) / 255
        b = int(value[4:6], 16) / 255
        return colors.Color(r, g, b)
    except ValueError:
        return fallback


def draw_watermark(canvas: Any, config: PdfConfig, page_size: tuple[float, float]) -> None:
    if not config.watermark.enabled or not config.watermark.text:
        return
    width, height = page_size
    canvas.saveState()
    try:
        canvas.setFillAlpha(config.watermark.opacity)
    except AttributeError:
        pass
    theme = resolve_reportlab_theme(config.theme)
    canvas.setFont(theme.font_family, theme.base_font_size * 4)
    canvas.setFillColor(colors.grey)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(30)
    canvas.drawCentredString(0, 0, config.watermark.text)
    canvas.restoreState()


def render_preview_pdf(resolved: PdfResolvedConfig) -> bytes:
    from reportlab.pdfgen import canvas as canvas_mod
    from io import BytesIO

    output = BytesIO()
    page_size = page_size_for_format(resolved.config.format)
    pdf = canvas_mod.Canvas(output, pagesize=page_size)
    width, height = page_size
    margin_top, margin_right, margin_bottom, margin_left = margins_for_format(resolved.config.format)
    theme = resolve_reportlab_theme(resolved.config.theme)

    apply_theme_reportlab(pdf, page_size, resolved.config.theme)
    draw_watermark(pdf, resolved.config, page_size)

    def draw_header() -> float:
        if not resolved.config.header.enabled:
            return height - margin_top
        title = resolved.config.header.title_template.format(
            module_title=resolved.module_label,
            module=resolved.module_key,
            generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
        pdf.setFillColor(theme.text_color)
        pdf.setFont(theme.font_family, theme.heading_font_size)
        pdf.drawString(margin_left, height - margin_top, title)
        pdf.setFont(theme.font_family, theme.base_font_size)
        pdf.setFillColor(theme.muted_text_color)
        subtitle = resolved.config.header.subtitle_template.format(
            module_title=resolved.module_label,
            module=resolved.module_key,
            generated_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
        pdf.drawString(margin_left, height - margin_top - 16, subtitle)
        return height - margin_top - 32

    def draw_footer(page_number: int) -> None:
        if not resolved.config.footer.enabled:
            return
        footer_bits: list[str] = []
        if resolved.config.footer.text:
            footer_bits.append(resolved.config.footer.text)
        if resolved.config.footer.show_printed_at:
            footer_bits.append(datetime.now().strftime("Édité le %d/%m/%Y %H:%M"))
        if resolved.config.footer.show_pagination:
            footer_bits.append(f"Page {page_number}")
        footer_text = " — ".join(footer_bits)
        pdf.setFillColor(theme.muted_text_color)
        pdf.setFont(theme.font_family, theme.base_font_size - 1)
        pdf.drawRightString(width - margin_right, margin_bottom - 4, footer_text)

    y = draw_header()
    pdf.setFillColor(theme.text_color)
    pdf.setFont(theme.font_family, theme.base_font_size)
    paragraph_lines = [
        "Ce paragraphe illustre la couleur principale du texte.",
        "Vous pouvez ajuster police, tailles et accents dans l'onglet Thème.",
    ]
    for line in paragraph_lines:
        pdf.drawString(margin_left, y, line)
        y -= 14
    pdf.setFillColor(theme.muted_text_color)
    pdf.drawString(margin_left, y, "Texte secondaire pour les informations contextuelles.")
    y -= 20
    pdf.setFillColor(theme.text_color)
    pdf.setFont(theme.font_family, theme.base_font_size + 1)
    pdf.drawString(margin_left, y, "Aperçu de tableau")
    y -= 18
    pdf.setFont(theme.font_family, theme.base_font_size)
    columns = resolved.config.content.columns or [
        PdfColumnConfig(key="col1", label="Colonne 1", visible=True),
        PdfColumnConfig(key="col2", label="Colonne 2", visible=True),
    ]
    visible_columns = [col for col in columns if col.visible]
    if not visible_columns:
        visible_columns = columns[:1]
    table_width = width - margin_left - margin_right
    column_width = table_width / len(visible_columns)
    header_height = 16
    pdf.setFillColor(theme.table_header_bg)
    pdf.rect(margin_left, y - header_height + 10, table_width, header_height, stroke=0, fill=1)
    pdf.setFillColor(theme.table_header_text)
    pdf.setStrokeColor(theme.border_color)
    pdf.rect(margin_left, y - header_height + 10, table_width, header_height, stroke=1, fill=0)
    for index, column in enumerate(visible_columns):
        x = margin_left + index * column_width
        pdf.drawString(x + 4, y, column.label)
    y -= 18
    for row in range(6):
        if row % 2 == 1:
            pdf.setFillColor(theme.table_row_alt_bg)
            pdf.rect(margin_left, y - 10, table_width, 14, stroke=0, fill=1)
            pdf.setFillColor(theme.text_color)
        for index, column in enumerate(visible_columns):
            x = margin_left + index * column_width
            pdf.drawString(x + 4, y, f"{column.label} {row + 1}")
        y -= 12

    draw_footer(1)
    pdf.showPage()
    apply_theme_reportlab(pdf, page_size, resolved.config.theme)
    draw_watermark(pdf, resolved.config, page_size)
    y = draw_header()
    pdf.setFillColor(theme.text_color)
    pdf.setFont(theme.font_family, theme.base_font_size)
    pdf.drawString(margin_left, y, "Page de démonstration supplémentaire.")
    draw_footer(2)
    pdf.save()
    return output.getvalue()


def render_filename(pattern: str, *, module_key: str, module_title: str, context: dict[str, Any] | None = None) -> str:
    now = datetime.now()
    variables = {
        "module": module_key,
        "module_title": module_title,
        "date": now,
        "generated_at": now.strftime("%d/%m/%Y %H:%M"),
    }
    if context:
        variables.update(context)
    try:
        filename = pattern.format(**variables)
    except Exception:
        filename = f"{module_key}_{now.strftime('%Y%m%d_%H%M')}.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    return filename

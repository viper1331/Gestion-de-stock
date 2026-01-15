"""PDF export configuration service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from reportlab.lib import colors
import math

from reportlab.lib.pagesizes import A3, A4, A5, letter, landscape, portrait
from reportlab.lib.units import mm

from backend.core.pdf_config_models import (
    PdfAdvancedConfig,
    PdfBrandingConfig,
    PdfColumnConfig,
    PdfColumnMeta,
    PdfGroupableColumnMeta,
    PdfModuleGroupingMeta,
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
from backend.core.pdf_registry import (
    normalize_pdf_module_key,
    pdf_module_label,
)
from backend.services.pdf.theme import (
    apply_theme_reportlab,
    resolve_reportlab_theme,
    scale_reportlab_theme,
    theme_meta,
)
from backend.services.pdf.grouping import build_group_tree, compute_group_stats


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
        "inventory_vehicles": PdfModuleMeta(
            key="inventory_vehicles",
            label=pdf_module_label("inventory_vehicles"),
            variables=["module", "module_title", "date", "generated_at", "vehicle"],
            grouping_supported=False,
            columns=[
                PdfColumnMeta(key="name", label="Matériel", default_visible=True, column_type="string"),
                PdfColumnMeta(
                    key="quantity",
                    label="Quantité",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
                PdfColumnMeta(key="size", label="Taille / Variante", default_visible=True, column_type="string"),
                PdfColumnMeta(key="category", label="Catégorie", default_visible=True, column_type="string"),
                PdfColumnMeta(key="lots", label="Lot(s)", default_visible=True, column_type="string"),
                PdfColumnMeta(key="expiration", label="Péremption", default_visible=True, column_type="date"),
                PdfColumnMeta(
                    key="threshold",
                    label="Seuil",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
            ],
            sort_options=["nom", "catégorie", "emplacement"],
            group_options=["catégorie", "emplacement"],
            renderers=["html", "reportlab"],
        ),
        "inventory_remises": PdfModuleMeta(
            key="inventory_remises",
            label=pdf_module_label("inventory_remises"),
            variables=["module", "module_title", "date", "generated_at"],
            grouping_supported=True,
            columns=[
                PdfColumnMeta(key="name", label="Matériel", default_visible=True, column_type="string"),
                PdfColumnMeta(
                    key="quantity",
                    label="Quantité",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
                PdfColumnMeta(key="size", label="Taille / Variante", default_visible=True, column_type="string"),
                PdfColumnMeta(key="category", label="Catégorie", default_visible=True, column_type="string"),
                PdfColumnMeta(key="lots", label="Lot(s)", default_visible=True, column_type="string"),
                PdfColumnMeta(key="expiration", label="Péremption", default_visible=True, column_type="date"),
                PdfColumnMeta(
                    key="threshold",
                    label="Seuil",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
            ],
            sort_options=["nom", "catégorie", "emplacement"],
            group_options=["catégorie"],
            renderers=["reportlab"],
        ),
        "orders": PdfModuleMeta(
            key="orders",
            label=pdf_module_label("orders"),
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            grouping_supported=True,
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True, column_type="string"),
                PdfColumnMeta(
                    key="ordered",
                    label="Commandé",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
                PdfColumnMeta(
                    key="received",
                    label="Réceptionné",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "orders_remises": PdfModuleMeta(
            key="orders_remises",
            label=pdf_module_label("orders_remises"),
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            grouping_supported=True,
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True, column_type="string"),
                PdfColumnMeta(
                    key="ordered",
                    label="Commandé",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
                PdfColumnMeta(
                    key="received",
                    label="Réceptionné",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "orders_pharmacy": PdfModuleMeta(
            key="orders_pharmacy",
            label=pdf_module_label("orders_pharmacy"),
            variables=["module", "module_title", "date", "generated_at", "order_id"],
            grouping_supported=True,
            columns=[
                PdfColumnMeta(key="article", label="Article", default_visible=True, column_type="string"),
                PdfColumnMeta(
                    key="ordered",
                    label="Commandé",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
                PdfColumnMeta(
                    key="received",
                    label="Réceptionné",
                    default_visible=True,
                    is_numeric=True,
                    column_type="number",
                ),
            ],
            sort_options=["nom"],
            group_options=[],
            renderers=["reportlab"],
        ),
        "barcodes": PdfModuleMeta(
            key="barcodes",
            label=pdf_module_label("barcodes"),
            variables=["module", "module_title", "date", "generated_at"],
            grouping_supported=False,
            columns=[
                PdfColumnMeta(key="barcode", label="Code-barres", default_visible=True, column_type="string"),
            ],
            sort_options=[],
            group_options=[],
            renderers=["reportlab"],
        ),
        "inventory_pharmacy": PdfModuleMeta(
            key="inventory_pharmacy",
            label=pdf_module_label("inventory_pharmacy"),
            variables=["module", "module_title", "date", "generated_at"],
            grouping_supported=False,
            columns=[],
            sort_options=[],
            group_options=[],
            renderers=["reportlab"],
        ),
        "inventory_habillement": PdfModuleMeta(
            key="inventory_habillement",
            label=pdf_module_label("inventory_habillement"),
            variables=["module", "module_title", "date", "generated_at"],
            grouping_supported=False,
            columns=[],
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
    for raw_key, module in (data.get("modules") or {}).items():
        key = normalize_pdf_module_key(raw_key)
        if key in modules and raw_key != key:
            continue
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


def _build_groupable_columns(columns: list[PdfColumnMeta]) -> list[PdfGroupableColumnMeta]:
    return [
        PdfGroupableColumnMeta(
            key=column.key,
            label=column.label,
            is_numeric=column.is_numeric,
            is_visible_by_default=column.default_visible,
            column_type=column.column_type,
        )
        for column in columns
    ]


def get_pdf_config_meta() -> dict[str, object]:
    meta = theme_meta()
    groupable_columns: list[PdfGroupableColumnMeta] = []
    seen_keys: set[str] = set()
    module_grouping: dict[str, PdfModuleGroupingMeta] = {}
    for module in get_module_meta().values():
        module_groupable = _build_groupable_columns(module.columns)
        module_grouping[module.key] = PdfModuleGroupingMeta(
            grouping_supported=bool(module.columns) and module.grouping_supported,
            groupable_columns=module_groupable,
        )
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
                    column_type=column.column_type,
                )
            )
    meta["groupableColumns"] = groupable_columns
    meta["moduleGrouping"] = module_grouping
    return meta


def _validate_grouping_config(module_key: str, config: PdfConfig, module_meta: PdfModuleMeta | None) -> None:
    if not module_meta:
        return
    column_keys = {column.key for column in module_meta.columns}
    grouping = config.grouping
    invalid_keys: list[str] = []

    grouping_keys = [key for key in grouping.keys if key]
    if len(grouping_keys) != len(set(grouping_keys)):
        raise ValueError(f"Clés de regroupement du module '{module_key}' en double.")

    invalid_keys.extend([key for key in grouping_keys if key not in column_keys])
    if config.content.group_by and config.content.group_by not in column_keys:
        invalid_keys.append(config.content.group_by)

    invalid_subtotals = [key for key in grouping.subtotal_columns if key not in column_keys]

    if (
        (not module_meta.grouping_supported or not column_keys)
        and (grouping_keys or grouping.subtotal_columns or config.content.group_by)
    ):
        raise ValueError(f"Le module '{module_key}' ne supporte pas le regroupement.")

    if invalid_keys or invalid_subtotals:
        missing = ", ".join(sorted(set(invalid_keys + invalid_subtotals)))
        raise ValueError(
            f"Clé(s) de regroupement invalide(s) pour le module '{module_key}' : {missing}."
        )


def _ensure_module_columns(module_key: str, config: PdfConfig) -> PdfConfig:
    meta = get_module_meta().get(normalize_pdf_module_key(module_key))
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
    module_meta = get_module_meta()

    for raw_key, module_cfg in payload.modules.items():
        key = normalize_pdf_module_key(raw_key)
        if not module_cfg.override_global:
            if module_cfg.config:
                module_overrides[key] = PdfModuleConfig(override_global=False, config=PdfConfigOverrides())
            continue

        if isinstance(module_cfg.config, PdfConfig):
            full_config = module_cfg.config
        else:
            full_config = _apply_overrides(global_config, module_cfg.config)
        _validate_grouping_config(key, full_config, module_meta.get(key))
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
    canonical_key = normalize_pdf_module_key(module_name)
    meta = export_config.module_meta.get(canonical_key) or get_module_meta().get(canonical_key)
    if not meta:
        meta = PdfModuleMeta(key=canonical_key, label=pdf_module_label(module_name), renderers=["reportlab"])
    resolved = export_config.global_config.model_copy(deep=True)

    preset = export_config.presets.get(preset_name) if preset_name else None
    if preset:
        resolved = preset.config.model_copy(deep=True)

    module_cfg = export_config.modules.get(canonical_key) or export_config.modules.get(module_name)
    if module_cfg and module_cfg.override_global:
        overrides = module_cfg.config
        if isinstance(overrides, PdfConfig):
            resolved = overrides.model_copy(deep=True)
        else:
            resolved = _apply_overrides(resolved, overrides)

    resolved = _ensure_module_columns(module_name, resolved)
    _validate_grouping_config(module_name, resolved, meta)
    return PdfResolvedConfig(
        module_key=module_name,
        module_label=meta.label,
        config=resolved,
        variables=meta.variables,
        renderers=meta.renderers,
    )


def page_size_for_format(format_config: PdfFormatConfig) -> tuple[float, float]:
    size_map = {"A3": A3, "A4": A4, "A5": A5, "Letter": letter}
    base = size_map.get(format_config.size, A4)
    if format_config.orientation == "landscape":
        return landscape(base)
    return portrait(base)


def effective_density_scale(format_config: PdfFormatConfig) -> float:
    if format_config.size != "A3":
        return 1.0
    format_scale = math.sqrt(2)
    density_factor = 0.9 if format_config.density == "compact" else 1.0
    return format_scale * density_factor


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


def draw_watermark(
    canvas: Any, config: PdfConfig, page_size: tuple[float, float], *, scale: float = 1.0
) -> None:
    if not config.watermark.enabled or not config.watermark.text:
        return
    width, height = page_size
    canvas.saveState()
    try:
        canvas.setFillAlpha(config.watermark.opacity)
    except AttributeError:
        pass
    theme = resolve_reportlab_theme(config.theme)
    theme = scale_reportlab_theme(theme, scale)
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
    scale = effective_density_scale(resolved.config.format)
    pdf = canvas_mod.Canvas(output, pagesize=page_size)
    width, height = page_size
    margin_top, margin_right, margin_bottom, margin_left = margins_for_format(resolved.config.format)
    theme = scale_reportlab_theme(resolve_reportlab_theme(resolved.config.theme), scale)

    apply_theme_reportlab(pdf, page_size, resolved.config.theme, scale=scale)
    draw_watermark(pdf, resolved.config, page_size, scale=scale)

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
        pdf.drawString(margin_left, height - margin_top - (16 * scale), subtitle)
        return height - margin_top - (32 * scale)

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
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        pdf.drawRightString(width - margin_right, margin_bottom - (4 * scale), footer_text)

    y = draw_header()
    pdf.setFillColor(theme.text_color)
    pdf.setFont(theme.font_family, theme.base_font_size)
    paragraph_lines = [
        "Ce paragraphe illustre la couleur principale du texte.",
        "Vous pouvez ajuster police, tailles et accents dans l'onglet Thème.",
    ]
    for line in paragraph_lines:
        pdf.drawString(margin_left, y, line)
        y -= 14 * scale
    pdf.setFillColor(theme.muted_text_color)
    pdf.drawString(margin_left, y, "Texte secondaire pour les informations contextuelles.")
    y -= 20 * scale
    pdf.setFillColor(theme.text_color)
    pdf.setFont(theme.font_family, theme.base_font_size + (1 * scale))
    pdf.drawString(margin_left, y, "Aperçu de tableau")
    y -= 18 * scale
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
    header_height = 16 * scale
    pdf.setFillColor(theme.table_header_bg)
    pdf.rect(margin_left, y - header_height + (10 * scale), table_width, header_height, stroke=0, fill=1)
    pdf.setFillColor(theme.table_header_text)
    pdf.setStrokeColor(theme.border_color)
    pdf.rect(margin_left, y - header_height + (10 * scale), table_width, header_height, stroke=1, fill=0)
    for index, column in enumerate(visible_columns):
        x = margin_left + index * column_width
        pdf.drawString(x + (4 * scale), y, column.label)
    y -= 18 * scale
    grouping = resolved.config.grouping
    grouping_keys = [key for key in grouping.keys if key]
    if grouping.enabled and not grouping_keys and resolved.config.content.group_by:
        grouping_keys = [resolved.config.content.group_by]

    label_map = {column.key: column.label for column in visible_columns}
    table_rows: list[dict[str, dict[str, object]]] = []
    for row in range(6):
        display: dict[str, object] = {}
        raw: dict[str, object] = {}
        for column in visible_columns:
            if column.key in grouping_keys:
                group_value = f"{column.label} {row // 3 + 1}"
                display[column.key] = group_value
                raw[column.key] = group_value
            elif column.key in grouping.subtotal_columns:
                value = (row + 1) * 2
                display[column.key] = str(value)
                raw[column.key] = value
            else:
                value = f"{column.label} {row + 1}"
                display[column.key] = value
                raw[column.key] = value
        table_rows.append({"display": display, "raw": raw})

    def draw_row(row_data: dict[str, dict[str, object]], row_index: int) -> None:
        nonlocal y
        if row_index % 2 == 1:
            pdf.setFillColor(theme.table_row_alt_bg)
            pdf.rect(margin_left, y - (10 * scale), table_width, 14 * scale, stroke=0, fill=1)
            pdf.setFillColor(theme.text_color)
        for index, column in enumerate(visible_columns):
            x = margin_left + index * column_width
            value = row_data["display"].get(column.key, "")
            pdf.drawString(x + (4 * scale), y, str(value))
        y -= 12 * scale

    def draw_group_header(group_key: str, group_value: object, count: int) -> None:
        nonlocal y
        if grouping.header_style == "none":
            return
        label = label_map.get(group_key, group_key)
        value = group_value if group_value not in (None, "") else "—"
        header_text = f"{label} : {value}"
        if grouping.show_counts:
            header_text = f"{header_text} ({count})"
        header_height = 14 * scale
        if grouping.header_style == "bar":
            pdf.setFillColor(theme.table_header_bg)
            pdf.rect(margin_left, y - header_height + (10 * scale), table_width, header_height, stroke=0, fill=1)
            pdf.setFillColor(theme.table_header_text)
        else:
            pdf.setFillColor(theme.text_color)
        pdf.setFont(theme.font_family, theme.base_font_size)
        pdf.drawString(margin_left + (4 * scale), y, header_text)
        pdf.setFillColor(theme.text_color)
        y -= 12 * scale

    def draw_subtotal(subtotals: dict[str, float], row_index: int) -> int:
        nonlocal y
        if not grouping.show_subtotals or not grouping.subtotal_columns:
            return row_index
        display = {column.key: "" for column in visible_columns}
        if visible_columns:
            display[visible_columns[0].key] = "Sous-total"
        for key, value in subtotals.items():
            display[key] = str(int(value) if value.is_integer() else value)
        draw_row({"display": display, "raw": {}}, row_index)
        return row_index + 1

    if grouping.enabled and grouping_keys:
        group_tree = build_group_tree(
            table_rows,
            grouping_keys,
            key_fn=lambda row, key: row["raw"].get(key),
        )

        def render_group(group, *, level: int, row_index: int) -> int:
            stats = compute_group_stats(
                group,
                subtotal_columns=grouping.subtotal_columns,
                value_fn=lambda row, key: row["raw"].get(key),
            )
            count = stats.row_count if grouping.counts_scope == "leaf" else (
                stats.child_count if group.children else stats.row_count
            )
            draw_group_header(group.key, group.value, count)
            if group.children:
                for child in group.children:
                    row_index = render_group(child, level=level + 1, row_index=row_index)
            else:
                for row in group.rows:
                    draw_row(row, row_index)
                    row_index += 1
            if not (grouping.subtotal_scope == "leaf" and group.children):
                row_index = draw_subtotal(stats.subtotals, row_index)
            return row_index

        row_index = 0
        for group in group_tree:
            row_index = render_group(group, level=0, row_index=row_index)
    else:
        for row_index, row in enumerate(table_rows):
            draw_row(row, row_index)

    draw_footer(1)
    pdf.showPage()
    apply_theme_reportlab(pdf, page_size, resolved.config.theme, scale=scale)
    draw_watermark(pdf, resolved.config, page_size, scale=scale)
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

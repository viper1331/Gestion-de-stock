import { api } from "./api";

export type PdfOrientation = "portrait" | "landscape";
export type PdfPageSize = "A4" | "A5" | "Letter";
export type PdfMarginPreset = "normal" | "narrow" | "wide" | "custom";
export type PdfDensity = "comfort" | "standard" | "compact";

export interface PdfMargins {
  top_mm: number;
  right_mm: number;
  bottom_mm: number;
  left_mm: number;
}

export interface PdfFormatConfig {
  size: PdfPageSize;
  orientation: PdfOrientation;
  margin_preset: PdfMarginPreset;
  margins: PdfMargins;
  density: PdfDensity;
}

export interface PdfBrandingConfig {
  logo_enabled: boolean;
  logo_url?: string | null;
  logo_path?: string | null;
  logo_width_mm: number;
  logo_position: "left" | "center" | "right";
  company_name?: string | null;
  accent_color?: string | null;
}

export interface PdfHeaderConfig {
  enabled: boolean;
  title_template: string;
  subtitle_template: string;
  info_keys: string[];
}

export interface PdfColumnConfig {
  key: string;
  label: string;
  visible: boolean;
}

export interface PdfContentConfig {
  columns: PdfColumnConfig[];
  sort_by?: string | null;
  group_by?: string | null;
  show_totals: boolean;
}

export interface PdfFooterConfig {
  enabled: boolean;
  show_pagination: boolean;
  show_printed_at: boolean;
  text?: string | null;
}

export interface PdfWatermarkConfig {
  enabled: boolean;
  text: string;
  opacity: number;
}

export interface PdfFilenameConfig {
  pattern: string;
}

export interface PdfAdvancedConfig {
  font_family: string;
  base_font_size: number;
  header_bg_color: string;
  header_text_color: string;
  table_header_bg_color: string;
  table_header_text_color: string;
  row_alt_bg_color: string;
}

export interface PdfThemeConfig {
  font_family: string;
  base_font_size: number;
  heading_font_size: number;
  text_color: string;
  muted_text_color: string;
  accent_color: string;
  table_header_bg: string;
  table_header_text: string;
  table_row_alt_bg: string;
  border_color: string;
  background_mode: "none" | "color" | "image";
  background_color: string;
  background_image?: string | null;
  background_opacity: number;
  background_fit: "cover" | "contain";
  background_position: string;
}

export interface PdfConfig {
  format: PdfFormatConfig;
  branding: PdfBrandingConfig;
  header: PdfHeaderConfig;
  content: PdfContentConfig;
  footer: PdfFooterConfig;
  watermark: PdfWatermarkConfig;
  filename: PdfFilenameConfig;
  advanced: PdfAdvancedConfig;
  theme: PdfThemeConfig;
}

export interface PdfModuleConfig {
  override_global: boolean;
  config: PdfConfig | Partial<PdfConfig>;
}

export interface PdfPresetConfig {
  name: string;
  config: PdfConfig;
}

export interface PdfColumnMeta {
  key: string;
  label: string;
  default_visible: boolean;
}

export interface PdfModuleMeta {
  key: string;
  label: string;
  variables: string[];
  columns: PdfColumnMeta[];
  sort_options: string[];
  group_options: string[];
  renderers: Array<"html" | "reportlab">;
}

export interface PdfExportConfig {
  global_config: PdfConfig;
  modules: Record<string, PdfModuleConfig>;
  presets: Record<string, PdfPresetConfig>;
  module_meta: Record<string, PdfModuleMeta>;
}

export interface PdfConfigMeta {
  supported_fonts: string[];
  accepted_color_formats: string[];
  renderer_compatibility: Record<string, Record<string, unknown>>;
}

export const DEFAULT_PDF_FORMAT: PdfFormatConfig = {
  size: "A4",
  orientation: "portrait",
  margin_preset: "normal",
  margins: { top_mm: 15, right_mm: 15, bottom_mm: 15, left_mm: 15 },
  density: "standard"
};

export const DEFAULT_PDF_BRANDING: PdfBrandingConfig = {
  logo_enabled: true,
  logo_url: null,
  logo_path: null,
  logo_width_mm: 24,
  logo_position: "left",
  company_name: "Gestion Stock Pro",
  accent_color: "#4f46e5"
};

export const DEFAULT_PDF_HEADER: PdfHeaderConfig = {
  enabled: true,
  title_template: "{module_title}",
  subtitle_template: "Généré le {generated_at}",
  info_keys: []
};

export const DEFAULT_PDF_CONTENT: PdfContentConfig = {
  columns: [],
  sort_by: null,
  group_by: null,
  show_totals: false
};

export const DEFAULT_PDF_FOOTER: PdfFooterConfig = {
  enabled: true,
  show_pagination: true,
  show_printed_at: true,
  text: null
};

export const DEFAULT_PDF_WATERMARK: PdfWatermarkConfig = {
  enabled: false,
  text: "CONFIDENTIEL",
  opacity: 0.08
};

export const DEFAULT_PDF_FILENAME: PdfFilenameConfig = {
  pattern: "{module}_{date:%Y%m%d_%H%M}.pdf"
};

export const DEFAULT_PDF_ADVANCED: PdfAdvancedConfig = {
  font_family: "Helvetica",
  base_font_size: 10,
  header_bg_color: "#111827",
  header_text_color: "#f8fafc",
  table_header_bg_color: "#1f2937",
  table_header_text_color: "#f8fafc",
  row_alt_bg_color: "#0f172a"
};

export const DEFAULT_PDF_THEME: PdfThemeConfig = {
  font_family: "Helvetica",
  base_font_size: 10,
  heading_font_size: 14,
  text_color: "#111827",
  muted_text_color: "#64748b",
  accent_color: "#4f46e5",
  table_header_bg: "#1f2937",
  table_header_text: "#f8fafc",
  table_row_alt_bg: "#f1f5f9",
  border_color: "#e2e8f0",
  background_mode: "none",
  background_color: "#ffffff",
  background_image: "",
  background_opacity: 1,
  background_fit: "cover",
  background_position: "center"
};

export const DEFAULT_PDF_CONFIG: PdfConfig = {
  format: DEFAULT_PDF_FORMAT,
  branding: DEFAULT_PDF_BRANDING,
  header: DEFAULT_PDF_HEADER,
  content: DEFAULT_PDF_CONTENT,
  footer: DEFAULT_PDF_FOOTER,
  watermark: DEFAULT_PDF_WATERMARK,
  filename: DEFAULT_PDF_FILENAME,
  advanced: DEFAULT_PDF_ADVANCED,
  theme: DEFAULT_PDF_THEME
};

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export const deepMerge = <T,>(base: T, overrides?: Partial<T> | null): T => {
  if (!overrides) return base;
  const baseValue = base as Record<string, unknown>;
  const result: Record<string, unknown> = { ...baseValue };
  Object.entries(overrides).forEach(([key, value]) => {
    if (value === null && isPlainObject(baseValue[key])) {
      return;
    }
    if (Array.isArray(value)) {
      result[key] = value;
      return;
    }
    if (isPlainObject(value) && isPlainObject(baseValue[key])) {
      result[key] = deepMerge(baseValue[key], value as Partial<T>);
      return;
    }
    if (value !== undefined) {
      result[key] = value;
    }
  });
  return result as T;
};

export const normalizePdfConfig = (raw?: Partial<PdfConfig> | null): PdfConfig =>
  deepMerge(structuredClone(DEFAULT_PDF_CONFIG), raw ?? {});

export const normalizePdfExportConfig = (raw: PdfExportConfig): PdfExportConfig => {
  const globalConfig = normalizePdfConfig(raw.global_config ?? null);
  const presets: Record<string, PdfPresetConfig> = {};
  Object.entries(raw.presets ?? {}).forEach(([name, preset]) => {
    presets[name] = {
      ...preset,
      config: normalizePdfConfig(preset?.config ?? null)
    };
  });
  const modules: Record<string, PdfModuleConfig> = {};
  Object.entries(raw.modules ?? {}).forEach(([key, moduleConfig]) => {
    const overrideGlobal = moduleConfig?.override_global ?? false;
    const rawModuleConfig = moduleConfig?.config ?? {};
    modules[key] = {
      ...moduleConfig,
      override_global: overrideGlobal,
      config: overrideGlobal
        ? normalizePdfConfig(deepMerge(globalConfig, rawModuleConfig as Partial<PdfConfig>))
        : (rawModuleConfig ?? {})
    };
  });
  return {
    ...raw,
    global_config: globalConfig,
    presets,
    modules
  };
};

export async function fetchPdfConfig(): Promise<PdfExportConfig> {
  const { data } = await api.get<PdfExportConfig>("/admin/pdf-config");
  return normalizePdfExportConfig(data);
}

export async function updatePdfConfig(payload: PdfExportConfig): Promise<PdfExportConfig> {
  const { data } = await api.post<PdfExportConfig>("/admin/pdf-config", payload);
  return data;
}

export async function previewPdfConfig(payload: {
  module: string;
  preset?: string | null;
  config?: PdfExportConfig | null;
}): Promise<Blob> {
  const { data } = await api.post("/admin/pdf-config/preview", payload, {
    responseType: "blob"
  });
  return data;
}

export async function fetchPdfConfigMeta(): Promise<PdfConfigMeta> {
  const { data } = await api.get<PdfConfigMeta>("/admin/pdf-config/meta");
  return data;
}

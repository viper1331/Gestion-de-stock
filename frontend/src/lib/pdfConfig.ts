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

export async function fetchPdfConfig(): Promise<PdfExportConfig> {
  const { data } = await api.get<PdfExportConfig>("/admin/pdf-config");
  return data;
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

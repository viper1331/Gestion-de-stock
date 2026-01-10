import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import {
  PdfColumnConfig,
  PdfConfig,
  PdfExportConfig,
  PdfModuleConfig,
  PdfModuleMeta,
  PdfThemeConfig,
  fetchPdfConfig,
  fetchPdfConfigMeta,
  previewPdfConfig,
  updatePdfConfig
} from "../../lib/pdfConfig";

const DEFAULT_PREVIEW_MESSAGE = "Utilisez le bouton Aperçu pour générer un PDF.";
const DEFAULT_THEME: PdfThemeConfig = {
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

const LoadingState = () => (
  <section className="space-y-2">
    <h2 className="text-xl font-semibold text-white">PDF Studio</h2>
    <p className="text-sm text-slate-400">Chargement des configurations...</p>
  </section>
);

const toHexColor = (value: string, fallback = "#000000"): string => {
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  if (trimmed.toLowerCase() === "transparent") return fallback;
  const hexMatch = trimmed.match(/^#([0-9a-f]{3})$/i);
  if (hexMatch) {
    const [r, g, b] = hexMatch[1].split("");
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  const hexLong = trimmed.match(/^#([0-9a-f]{6})/i);
  if (hexLong) {
    return `#${hexLong[1]}`.toLowerCase();
  }
  const rgbaMatch = trimmed.match(/^rgba?\\(([^)]+)\\)$/i);
  if (rgbaMatch) {
    const parts = rgbaMatch[1].split(",").map((part) => part.trim());
    if (parts.length >= 3) {
      const r = Math.min(255, Math.max(0, Number(parts[0])));
      const g = Math.min(255, Math.max(0, Number(parts[1])));
      const b = Math.min(255, Math.max(0, Number(parts[2])));
      return (
        "#" +
        [r, g, b]
          .map((channel) => Math.round(channel).toString(16).padStart(2, "0"))
          .join("")
      );
    }
  }
  return fallback;
};

const colorToRgb = (value: string): { r: number; g: number; b: number } | null => {
  const hex = toHexColor(value, "");
  if (!hex || hex.length !== 7) return null;
  const r = Number.parseInt(hex.slice(1, 3), 16);
  const g = Number.parseInt(hex.slice(3, 5), 16);
  const b = Number.parseInt(hex.slice(5, 7), 16);
  return { r, g, b };
};

const contrastRatio = (foreground: string, background: string): number | null => {
  const fg = colorToRgb(foreground);
  const bg = colorToRgb(background);
  if (!fg || !bg) return null;
  const luminance = (color: { r: number; g: number; b: number }) => {
    const channel = (value: number) => {
      const scaled = value / 255;
      return scaled <= 0.03928 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  };
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  const light = Math.max(l1, l2);
  const dark = Math.min(l1, l2);
  return (light + 0.05) / (dark + 0.05);
};

type ColorFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onReset?: () => void;
};

const ColorField = ({ label, value, onChange, onReset }: ColorFieldProps) => (
  <label className="space-y-2 text-sm text-slate-200">
    <span className="flex items-center justify-between gap-2">
      {label}
      {onReset ? (
        <button type="button" onClick={onReset} className="text-xs text-indigo-300 hover:text-indigo-200">
          Réinitialiser
        </button>
      ) : null}
    </span>
    <div className="grid gap-2 sm:grid-cols-[120px_1fr]">
      <input
        type="color"
        value={toHexColor(value, "#000000")}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-md border border-slate-800 bg-slate-900 px-2"
      />
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
      />
    </div>
  </label>
);

const marginPresets: Record<string, PdfConfig["format"]["margins"]> = {
  normal: { top_mm: 15, right_mm: 15, bottom_mm: 15, left_mm: 15 },
  narrow: { top_mm: 10, right_mm: 10, bottom_mm: 10, left_mm: 10 },
  wide: { top_mm: 20, right_mm: 20, bottom_mm: 20, left_mm: 20 }
};

const deepMerge = <T,>(base: T, overrides?: Partial<T>): T => {
  if (!overrides) return base;
  const baseValue = base as Record<string, unknown>;
  const result: Record<string, unknown> = { ...baseValue };
  Object.entries(overrides).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      result[key] = value;
      return;
    }
    if (value && typeof value === "object" && typeof baseValue[key] === "object") {
      result[key] = deepMerge(baseValue[key], value as Partial<T>);
      return;
    }
    if (value !== undefined) {
      result[key] = value;
    }
  });
  return result as T;
};

const cloneConfig = (config: PdfConfig): PdfConfig => JSON.parse(JSON.stringify(config)) as PdfConfig;

const mergeThemes = (...themes: Array<Partial<PdfThemeConfig> | null | undefined>): PdfThemeConfig =>
  themes.reduce<PdfThemeConfig>((acc, theme) => ({ ...acc, ...(theme ?? {}) }), { ...DEFAULT_THEME });

const resolveModuleConfig = (
  exportConfig: PdfExportConfig,
  moduleKey: string,
  presetName: string | null
): PdfConfig => {
  const globalConfig = exportConfig.global_config;
  const presetConfig = presetName ? exportConfig.presets[presetName]?.config : undefined;
  const moduleConfig = exportConfig.modules[moduleKey];
  let resolved = cloneConfig(globalConfig);
  if (presetConfig) {
    resolved = deepMerge(resolved, presetConfig);
  }
  if (moduleConfig?.override_global) {
    resolved = deepMerge(resolved, moduleConfig.config as Partial<PdfConfig>);
  }
  return resolved;
};

const buildColumnDefaults = (meta?: PdfModuleMeta): PdfColumnConfig[] => {
  if (!meta) return [];
  return meta.columns.map((column) => ({
    key: column.key,
    label: column.label,
    visible: column.default_visible
  }));
};

const ensureColumns = (config: PdfConfig, meta?: PdfModuleMeta): PdfConfig => {
  if (config.content.columns.length > 0) return config;
  return {
    ...config,
    content: {
      ...config.content,
      columns: buildColumnDefaults(meta)
    }
  };
};

export function PdfStudioPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data: pdfConfig, isFetching, isLoading: isConfigLoading } = useQuery({
    queryKey: ["pdf-config"],
    queryFn: fetchPdfConfig,
    enabled: isAdmin
  });
  const { data: configMeta, isLoading: isMetaLoading } = useQuery({
    queryKey: ["pdf-config-meta"],
    queryFn: fetchPdfConfigMeta,
    enabled: isAdmin
  });
  const isLoading = isConfigLoading || isMetaLoading;
  const [draft, setDraft] = useState<PdfExportConfig | null>(null);
  const [initialConfig, setInitialConfig] = useState<PdfExportConfig | null>(null);
  const [selectedModule, setSelectedModule] = useState<string>("global");
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [autoPreview, setAutoPreview] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewStatus, setPreviewStatus] = useState<string>(DEFAULT_PREVIEW_MESSAGE);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (!pdfConfig) return;
    setDraft(pdfConfig);
    setInitialConfig(pdfConfig);
    const moduleKeys = Object.keys(pdfConfig.module_meta ?? {});
    if (moduleKeys.length > 0 && selectedModule && selectedModule !== "global") {
      if (!moduleKeys.includes(selectedModule)) {
        setSelectedModule(moduleKeys[0]);
      }
    }
    if (!selectedPreset) {
      const presets = Object.keys(pdfConfig.presets ?? {});
      setSelectedPreset(presets[0] ?? null);
    }
  }, [pdfConfig, selectedModule, selectedPreset]);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const moduleMeta = draft?.module_meta ?? {};
  const moduleOptions = useMemo(() => Object.values(moduleMeta), [moduleMeta]);
  const presetOptions = useMemo(() => Object.keys(draft?.presets ?? {}), [draft]);
  const supportedFonts = configMeta?.supported_fonts ?? ["Helvetica"];
  const acceptedColorFormats = configMeta?.accepted_color_formats ?? [];
  const reportlabNotes = useMemo(() => {
    const notes = configMeta?.renderer_compatibility?.reportlab?.notes;
    return Array.isArray(notes) ? notes : [];
  }, [configMeta]);

  const currentModuleMeta = selectedModule === "global" ? undefined : moduleMeta[selectedModule];
  const moduleConfig = draft?.modules[selectedModule];
  const isOverride = selectedModule !== "global" && moduleConfig?.override_global;
  const canResetTheme = selectedModule !== "global" && !!isOverride;

  const resolvedTheme = useMemo(() => {
    if (!draft) return DEFAULT_THEME;
    const globalTheme = draft.global_config?.theme;
    if (selectedModule === "global") {
      return mergeThemes(globalTheme);
    }
    const presetTheme = selectedPreset ? draft.presets[selectedPreset]?.config?.theme : undefined;
    const moduleTheme = moduleConfig?.override_global
      ? (moduleConfig.config as Partial<PdfConfig>)?.theme
      : undefined;
    return mergeThemes(globalTheme, presetTheme, moduleTheme);
  }, [draft, moduleConfig, selectedModule, selectedPreset]);

  const fallbackTheme = useMemo(() => {
    if (!draft) return DEFAULT_THEME;
    const globalTheme = draft.global_config?.theme;
    if (selectedModule === "global") {
      return mergeThemes(globalTheme);
    }
    const presetTheme = selectedPreset ? draft.presets[selectedPreset]?.config?.theme : undefined;
    return mergeThemes(globalTheme, presetTheme);
  }, [draft, selectedModule, selectedPreset]);

  const resolvedConfig = useMemo(() => {
    if (!draft) return null;
    if (selectedModule === "global") {
      return ensureColumns(
        { ...cloneConfig(draft.global_config), theme: mergeThemes(draft.global_config.theme) },
        currentModuleMeta
      );
    }
    const merged = resolveModuleConfig(draft, selectedModule, selectedPreset);
    return ensureColumns({ ...merged, theme: resolvedTheme }, currentModuleMeta);
  }, [draft, selectedModule, selectedPreset, currentModuleMeta, resolvedTheme]);

  const fallbackConfig = useMemo(() => {
    if (!draft) return null;
    if (selectedModule === "global") {
      return ensureColumns(
        { ...cloneConfig(draft.global_config), theme: mergeThemes(draft.global_config.theme) },
        currentModuleMeta
      );
    }
    const base = cloneConfig(draft.global_config);
    const presetConfig = selectedPreset ? draft.presets[selectedPreset]?.config : undefined;
    const merged = presetConfig ? deepMerge(base, presetConfig) : base;
    return ensureColumns({ ...merged, theme: fallbackTheme }, currentModuleMeta);
  }, [draft, selectedModule, selectedPreset, currentModuleMeta, fallbackTheme]);

  const contrastWarning = useMemo(() => {
    if (!resolvedConfig) return null;
    const theme = { ...DEFAULT_THEME, ...(resolvedTheme ?? {}) };
    const background = theme.background_mode === "color" ? theme.background_color : "#ffffff";
    const ratio = contrastRatio(theme.text_color, background);
    if (ratio !== null && ratio < 4.5) {
      return `Contraste faible (ratio ${ratio.toFixed(2)}).`;
    }
    return null;
  }, [resolvedConfig, resolvedTheme]);

  const editableConfig = useMemo(() => {
    if (!draft) return null;
    if (selectedModule === "global") {
      const config = cloneConfig(draft.global_config);
      return ensureColumns({ ...config, theme: mergeThemes(config.theme) }, currentModuleMeta);
    }
    if (moduleConfig?.override_global) {
      const config = cloneConfig(moduleConfig.config as PdfConfig);
      return ensureColumns({ ...config, theme: mergeThemes(config.theme) }, currentModuleMeta);
    }
    const config = cloneConfig(draft.global_config);
    return ensureColumns({ ...config, theme: mergeThemes(config.theme) }, currentModuleMeta);
  }, [draft, moduleConfig, selectedModule, currentModuleMeta]);

  const updateConfigState = useCallback(
    (updater: (config: PdfConfig) => PdfConfig) => {
      if (!draft || !editableConfig) return;
      const updated = updater(editableConfig);
      setDraft((prev) => {
        if (!prev) return prev;
        if (selectedModule === "global") {
          return { ...prev, global_config: updated };
        }
        const existingModule: PdfModuleConfig = prev.modules[selectedModule] ?? {
          override_global: false,
          config: {}
        };
        if (!existingModule.override_global) {
          return { ...prev, global_config: updated };
        }
        return {
          ...prev,
          modules: {
            ...prev.modules,
            [selectedModule]: { ...existingModule, config: updated }
          }
        };
      });
    },
    [draft, editableConfig, selectedModule]
  );

  const updateThemeField = useCallback(
    <K extends keyof PdfThemeConfig>(key: K, value: PdfThemeConfig[K]) => {
      updateConfigState((config) => ({
        ...config,
        theme: { ...config.theme, [key]: value }
      }));
    },
    [updateConfigState]
  );

  const resetThemeField = useCallback(
    (key: keyof PdfThemeConfig) => {
      if (!fallbackConfig) return;
      updateThemeField(key, fallbackConfig.theme[key]);
    },
    [fallbackConfig, updateThemeField]
  );

  const handleOverrideToggle = (value: boolean) => {
    if (!draft || selectedModule === "global") return;
    setDraft((prev) => {
      if (!prev) return prev;
      const nextModule = value
        ? {
            override_global: true,
            config: resolveModuleConfig(prev, selectedModule, selectedPreset)
          }
        : { override_global: false, config: {} };
      return { ...prev, modules: { ...prev.modules, [selectedModule]: nextModule } };
    });
  };

  const handlePreview = useCallback(async () => {
    if (!draft) return;
    const previewModule =
      selectedModule === "global"
        ? moduleOptions[0]?.key ?? "barcode"
        : selectedModule;
    setPreviewStatus("Génération de l'aperçu...");
    try {
      const blob = await previewPdfConfig({
        module: previewModule,
        preset: selectedPreset,
        config: draft
      });
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
      setPreviewStatus("Aperçu généré.");
    } catch {
      setPreviewStatus("Impossible de générer l'aperçu.");
    }
  }, [draft, moduleOptions, previewUrl, selectedModule, selectedPreset]);

  useEffect(() => {
    if (!autoPreview) return;
    if (!draft) return;
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      handlePreview();
    }, 800);
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [autoPreview, draft, handlePreview, selectedModule, selectedPreset]);

  const saveMutation = useMutation({
    mutationFn: updatePdfConfig,
    onSuccess: (payload) => {
      setDraft(payload);
      setInitialConfig(payload);
    }
  });

  const handleReset = () => {
    if (initialConfig) {
      setDraft(initialConfig);
    }
  };

  const handleDuplicate = () => {
    if (!draft) return;
    if (selectedModule === "global") return;
    setDraft((prev) => {
      if (!prev) return prev;
      const currentModule = prev.modules[selectedModule];
      if (currentModule?.override_global) {
        return { ...prev, global_config: currentModule.config as PdfConfig };
      }
      return {
        ...prev,
        modules: {
          ...prev.modules,
          [selectedModule]: {
            override_global: true,
            config: resolveModuleConfig(prev, selectedModule, selectedPreset)
          }
        }
      };
    });
  };

  const handleColumnsReorder = (targetKey: string) => {
    if (!editableConfig || !dragKey || dragKey === targetKey) return;
    const columns = [...editableConfig.content.columns];
    const fromIndex = columns.findIndex((column) => column.key === dragKey);
    const toIndex = columns.findIndex((column) => column.key === targetKey);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = columns.splice(fromIndex, 1);
    columns.splice(toIndex, 0, moved);
    updateConfigState((config) => ({
      ...config,
      content: { ...config.content, columns }
    }));
  };

  if (!isAdmin) {
    return (
      <section className="space-y-2">
        <h2 className="text-xl font-semibold text-white">Configuration PDF</h2>
        <p className="text-sm text-slate-400">Cette page est réservée aux administrateurs.</p>
      </section>
    );
  }

  if (isLoading || !pdfConfig || !configMeta) {
    return <LoadingState />;
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">PDF Studio</h2>
        <p className="text-sm text-slate-400">
          Personnalisez vos exports PDF module par module et validez immédiatement via l'aperçu intégré.
        </p>
      </header>
      {isFetching ? <p className="text-sm text-slate-400">Chargement des configurations...</p> : null}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-950 p-4">
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Module
          <select
            value={selectedModule}
            onChange={(event) => setSelectedModule(event.target.value)}
            className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100"
          >
            <option value="global">Global</option>
            {moduleOptions.map((module) => (
              <option key={module.key} value={module.key}>
                {module.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Preset
          <select
            value={selectedPreset ?? ""}
            onChange={(event) => setSelectedPreset(event.target.value)}
            className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100"
          >
            {presetOptions.map((preset) => (
              <option key={preset} value={preset}>
                {preset}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handlePreview}
            className="rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
          >
            Aperçu
          </button>
          <button
            type="button"
            onClick={() => draft && saveMutation.mutate(draft)}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-500"
          >
            Enregistrer
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
          >
            Réinitialiser
          </button>
          <button
            type="button"
            onClick={handleDuplicate}
            className="rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
            disabled={selectedModule === "global"}
          >
            Dupliquer
          </button>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          {selectedModule !== "global" ? (
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 p-4 text-sm text-slate-200">
              <div>
                <p className="font-semibold">Surcharger le global</p>
                <p className="text-xs text-slate-400">
                  Activez pour personnaliser ce module sans impacter le global.
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
                <input
                  type="checkbox"
                  checked={isOverride}
                  onChange={(event) => handleOverrideToggle(event.target.checked)}
                  className="h-4 w-4"
                />
                {isOverride ? "Actif" : "Inactif"}
              </label>
            </div>
          ) : null}
          {currentModuleMeta ? (
            <div className="flex flex-wrap gap-2 text-xs text-slate-300">
              {currentModuleMeta.renderers.map((renderer) => (
                <span
                  key={renderer}
                  className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1"
                >
                  Renderer: {renderer}
                </span>
              ))}
            </div>
          ) : null}
          <div className="space-y-3">
            <details open className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Format</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="space-y-1 text-sm text-slate-200">
                  Taille
                  <select
                    value={editableConfig?.format.size ?? "A4"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        format: { ...config.format, size: event.target.value as PdfConfig["format"]["size"] }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  >
                    <option value="A4">A4</option>
                    <option value="A5">A5</option>
                    <option value="Letter">Letter</option>
                  </select>
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Orientation
                  <select
                    value={editableConfig?.format.orientation ?? "portrait"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        format: {
                          ...config.format,
                          orientation: event.target.value as PdfConfig["format"]["orientation"]
                        }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  >
                    <option value="portrait">Portrait</option>
                    <option value="landscape">Paysage</option>
                  </select>
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Marges
                  <select
                    value={editableConfig?.format.margin_preset ?? "normal"}
                    onChange={(event) => {
                      const preset = event.target.value as PdfConfig["format"]["margin_preset"];
                      updateConfigState((config) => ({
                        ...config,
                        format: {
                          ...config.format,
                          margin_preset: preset,
                          margins: marginPresets[preset] ?? config.format.margins
                        }
                      }));
                    }}
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  >
                    <option value="normal">Normal</option>
                    <option value="narrow">Étroit</option>
                    <option value="wide">Large</option>
                    <option value="custom">Personnalisé</option>
                  </select>
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Densité
                  <select
                    value={editableConfig?.format.density ?? "standard"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        format: { ...config.format, density: event.target.value as PdfConfig["format"]["density"] }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  >
                    <option value="comfort">Confort</option>
                    <option value="standard">Standard</option>
                    <option value="compact">Compact</option>
                  </select>
                </label>
              </div>
              {editableConfig?.format.margin_preset === "custom" ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-4">
                  {(["top_mm", "right_mm", "bottom_mm", "left_mm"] as const).map((key) => (
                    <label key={key} className="space-y-1 text-xs text-slate-300">
                      {key.replace("_mm", "").toUpperCase()} (mm)
                      <input
                        type="number"
                        min={0}
                        value={editableConfig?.format.margins[key] ?? 0}
                        onChange={(event) =>
                          updateConfigState((config) => ({
                            ...config,
                            format: {
                              ...config.format,
                              margins: {
                                ...config.format.margins,
                                [key]: Number(event.target.value)
                              }
                            }
                          }))
                        }
                        className="w-full rounded-md border border-slate-800 bg-slate-900 px-2 py-1 text-sm"
                      />
                    </label>
                  ))}
                </div>
              ) : null}
            </details>
            <details open className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Branding</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.branding.logo_enabled ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: { ...config.branding, logo_enabled: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Afficher le logo
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Source logo (URL)
                  <input
                    type="text"
                    value={editableConfig?.branding.logo_url ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: { ...config.branding, logo_url: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Taille logo (mm)
                  <input
                    type="number"
                    min={10}
                    value={editableConfig?.branding.logo_width_mm ?? 24}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: { ...config.branding, logo_width_mm: Number(event.target.value) }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Position logo
                  <select
                    value={editableConfig?.branding.logo_position ?? "left"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: {
                          ...config.branding,
                          logo_position: event.target.value as PdfConfig["branding"]["logo_position"]
                        }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  >
                    <option value="left">Gauche</option>
                    <option value="center">Centre</option>
                    <option value="right">Droite</option>
                  </select>
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Nom société / service
                  <input
                    type="text"
                    value={editableConfig?.branding.company_name ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: { ...config.branding, company_name: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Couleur d'accent
                  <input
                    type="color"
                    value={editableConfig?.branding.accent_color ?? "#4f46e5"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        branding: { ...config.branding, accent_color: event.target.value }
                      }))
                    }
                    className="h-10 w-full rounded-md border border-slate-800 bg-slate-900 px-2"
                  />
                </label>
              </div>
            </details>
            <details className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">En-tête</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.header.enabled ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        header: { ...config.header, enabled: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Afficher l'en-tête
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Titre
                  <input
                    type="text"
                    value={editableConfig?.header.title_template ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        header: { ...config.header, title_template: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Sous-titre
                  <input
                    type="text"
                    value={editableConfig?.header.subtitle_template ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        header: { ...config.header, subtitle_template: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
              </div>
            </details>
            <details open className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Contenu (table)</summary>
              <div className="mt-4 space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="space-y-1 text-sm text-slate-200">
                    Tri
                    <select
                      value={editableConfig?.content.sort_by ?? ""}
                      onChange={(event) =>
                        updateConfigState((config) => ({
                          ...config,
                          content: { ...config.content, sort_by: event.target.value || null }
                        }))
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                    >
                      <option value="">Aucun</option>
                      {(currentModuleMeta?.sort_options ?? []).map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="space-y-1 text-sm text-slate-200">
                    Regroupement
                    <select
                      value={editableConfig?.content.group_by ?? ""}
                      onChange={(event) =>
                        updateConfigState((config) => ({
                          ...config,
                          content: { ...config.content, group_by: event.target.value || null }
                        }))
                      }
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                    >
                      <option value="">Aucun</option>
                      {(currentModuleMeta?.group_options ?? []).map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-200">
                    <input
                      type="checkbox"
                      checked={editableConfig?.content.show_totals ?? false}
                      onChange={(event) =>
                        updateConfigState((config) => ({
                          ...config,
                          content: { ...config.content, show_totals: event.target.checked }
                        }))
                      }
                      className="h-4 w-4"
                    />
                    Totaux
                  </label>
                </div>
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Colonnes
                  </p>
                  <div className="space-y-2">
                    {editableConfig?.content.columns.map((column) => (
                      <div
                        key={column.key}
                        draggable
                        onDragStart={() => setDragKey(column.key)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => handleColumnsReorder(column.key)}
                        className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                      >
                        <span className="flex items-center gap-2">
                          <span className="cursor-grab text-slate-500">⋮⋮</span>
                          {column.label}
                        </span>
                        <label className="flex items-center gap-2 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            checked={column.visible}
                            onChange={(event) =>
                              updateConfigState((config) => ({
                                ...config,
                                content: {
                                  ...config.content,
                                  columns: config.content.columns.map((entry) =>
                                    entry.key === column.key
                                      ? { ...entry, visible: event.target.checked }
                                      : entry
                                  )
                                }
                              }))
                            }
                            className="h-4 w-4"
                          />
                          Visible
                        </label>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        updateConfigState((config) => ({
                          ...config,
                          content: {
                            ...config.content,
                            columns: buildColumnDefaults(currentModuleMeta)
                          }
                        }))
                      }
                      className="text-xs text-indigo-300 hover:text-indigo-200"
                    >
                      Réinitialiser les colonnes
                    </button>
                  </div>
                </div>
              </div>
            </details>
            <details className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Pied de page</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.footer.enabled ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        footer: { ...config.footer, enabled: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Afficher le pied de page
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.footer.show_pagination ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        footer: { ...config.footer, show_pagination: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Pagination
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.footer.show_printed_at ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        footer: { ...config.footer, show_printed_at: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Date d'édition
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Texte libre
                  <input
                    type="text"
                    value={editableConfig?.footer.text ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        footer: { ...config.footer, text: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
              </div>
            </details>
            <details className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Filigrane</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={editableConfig?.watermark.enabled ?? false}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        watermark: { ...config.watermark, enabled: event.target.checked }
                      }))
                    }
                    className="h-4 w-4"
                  />
                  Activer
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Texte
                  <input
                    type="text"
                    value={editableConfig?.watermark.text ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        watermark: { ...config.watermark, text: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Opacité
                  <input
                    type="range"
                    min={0}
                    max={0.3}
                    step={0.02}
                    value={editableConfig?.watermark.opacity ?? 0.08}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        watermark: { ...config.watermark, opacity: Number(event.target.value) }
                      }))
                    }
                    className="w-full"
                  />
                </label>
              </div>
            </details>
            <details className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Nom du fichier</summary>
              <div className="mt-4 space-y-3">
                <label className="space-y-1 text-sm text-slate-200">
                  Pattern
                  <input
                    type="text"
                    value={editableConfig?.filename.pattern ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        filename: { ...config.filename, pattern: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <div className="flex flex-wrap gap-2 text-xs text-slate-400">
                  {(currentModuleMeta?.variables ?? ["module", "date"]).map((variable) => (
                    <span key={variable} className="rounded-full border border-slate-700 px-2 py-1">
                      {"{" + variable + "}"}
                    </span>
                  ))}
                </div>
              </div>
            </details>
            <details className="rounded-lg border border-slate-800 bg-slate-950 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Thème</summary>
              <div className="mt-4 space-y-6">
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="space-y-1 text-sm text-slate-200">
                    Police
                    <select
                      value={editableConfig?.theme.font_family ?? "Helvetica"}
                      onChange={(event) => updateThemeField("font_family", event.target.value)}
                      className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                    >
                      {supportedFonts.map((font) => (
                        <option key={font} value={font}>
                          {font}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="space-y-1 text-sm text-slate-200">
                    Taille base
                    <input
                      type="range"
                      min={8}
                      max={18}
                      step={1}
                      value={editableConfig?.theme.base_font_size ?? 10}
                      onChange={(event) => updateThemeField("base_font_size", Number(event.target.value))}
                      className="w-full"
                    />
                    <span className="text-xs text-slate-400">
                      {editableConfig?.theme.base_font_size ?? 10} pt
                    </span>
                  </label>
                  <label className="space-y-1 text-sm text-slate-200">
                    Taille titres
                    <input
                      type="range"
                      min={10}
                      max={24}
                      step={1}
                      value={editableConfig?.theme.heading_font_size ?? 14}
                      onChange={(event) => updateThemeField("heading_font_size", Number(event.target.value))}
                      className="w-full"
                    />
                    <span className="text-xs text-slate-400">
                      {editableConfig?.theme.heading_font_size ?? 14} pt
                    </span>
                  </label>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <ColorField
                    label="Texte"
                    value={editableConfig?.theme.text_color ?? "#111827"}
                    onChange={(value) => updateThemeField("text_color", value)}
                    onReset={canResetTheme ? () => resetThemeField("text_color") : undefined}
                  />
                  <ColorField
                    label="Texte secondaire"
                    value={editableConfig?.theme.muted_text_color ?? "#64748b"}
                    onChange={(value) => updateThemeField("muted_text_color", value)}
                    onReset={canResetTheme ? () => resetThemeField("muted_text_color") : undefined}
                  />
                  <ColorField
                    label="Accent"
                    value={editableConfig?.theme.accent_color ?? "#4f46e5"}
                    onChange={(value) => updateThemeField("accent_color", value)}
                    onReset={canResetTheme ? () => resetThemeField("accent_color") : undefined}
                  />
                  <ColorField
                    label="Header tableau"
                    value={editableConfig?.theme.table_header_bg ?? "#1f2937"}
                    onChange={(value) => updateThemeField("table_header_bg", value)}
                    onReset={canResetTheme ? () => resetThemeField("table_header_bg") : undefined}
                  />
                  <ColorField
                    label="Texte header tableau"
                    value={editableConfig?.theme.table_header_text ?? "#f8fafc"}
                    onChange={(value) => updateThemeField("table_header_text", value)}
                    onReset={canResetTheme ? () => resetThemeField("table_header_text") : undefined}
                  />
                  <ColorField
                    label="Alternance lignes"
                    value={editableConfig?.theme.table_row_alt_bg ?? "#f1f5f9"}
                    onChange={(value) => updateThemeField("table_row_alt_bg", value)}
                    onReset={canResetTheme ? () => resetThemeField("table_row_alt_bg") : undefined}
                  />
                  <ColorField
                    label="Bordures"
                    value={editableConfig?.theme.border_color ?? "#e2e8f0"}
                    onChange={(value) => updateThemeField("border_color", value)}
                    onReset={canResetTheme ? () => resetThemeField("border_color") : undefined}
                  />
                </div>
                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Fond</p>
                  <div className="flex flex-wrap gap-3 text-sm text-slate-200">
                    {(["none", "color", "image"] as const).map((mode) => (
                      <label key={mode} className="flex items-center gap-2">
                        <input
                          type="radio"
                          checked={editableConfig?.theme.background_mode === mode}
                          onChange={() => updateThemeField("background_mode", mode)}
                          className="h-4 w-4"
                        />
                        {mode === "none" ? "Aucun" : mode === "color" ? "Couleur" : "Image"}
                      </label>
                    ))}
                  </div>
                  {editableConfig?.theme.background_mode === "color" ? (
                    <ColorField
                      label="Couleur de fond"
                      value={editableConfig?.theme.background_color ?? "#ffffff"}
                      onChange={(value) => updateThemeField("background_color", value)}
                      onReset={canResetTheme ? () => resetThemeField("background_color") : undefined}
                    />
                  ) : null}
                  {editableConfig?.theme.background_mode === "image" ? (
                    <div className="grid gap-4 sm:grid-cols-2">
                      <label className="space-y-1 text-sm text-slate-200">
                        Image (URL / chemin)
                        <input
                          type="text"
                          value={editableConfig?.theme.background_image ?? ""}
                          onChange={(event) => updateThemeField("background_image", event.target.value)}
                          className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                        />
                      </label>
                      <label className="space-y-1 text-sm text-slate-200">
                        Ajustement
                        <select
                          value={editableConfig?.theme.background_fit ?? "cover"}
                          onChange={(event) =>
                            updateThemeField("background_fit", event.target.value as PdfThemeConfig["background_fit"])
                          }
                          className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                        >
                          <option value="cover">Cover</option>
                          <option value="contain">Contain</option>
                        </select>
                      </label>
                      <label className="space-y-1 text-sm text-slate-200">
                        Position
                        <input
                          type="text"
                          value={editableConfig?.theme.background_position ?? "center"}
                          onChange={(event) => updateThemeField("background_position", event.target.value)}
                          className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                        />
                      </label>
                    </div>
                  ) : null}
                  <label className="space-y-1 text-sm text-slate-200">
                    Opacité
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={editableConfig?.theme.background_opacity ?? 1}
                      onChange={(event) => updateThemeField("background_opacity", Number(event.target.value))}
                      className="w-full"
                    />
                    <span className="text-xs text-slate-400">
                      {editableConfig?.theme.background_opacity ?? 1}
                    </span>
                  </label>
                </div>
                {contrastWarning ? (
                  <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                    {contrastWarning}
                  </p>
                ) : null}
                {acceptedColorFormats.length > 0 ? (
                  <p className="text-xs text-slate-400">
                    Formats couleur acceptés : {acceptedColorFormats.join(", ")}.
                  </p>
                ) : null}
                {reportlabNotes.length > 0 ? (
                  <div className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300">
                    <p className="font-semibold text-slate-200">Compatibilité ReportLab</p>
                    <ul className="mt-1 list-disc space-y-1 pl-4">
                      {reportlabNotes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </details>
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 p-4">
            <div>
              <p className="text-sm font-semibold text-slate-200">Aperçu PDF</p>
              <p className="text-xs text-slate-400">{previewStatus}</p>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={autoPreview}
                onChange={(event) => setAutoPreview(event.target.checked)}
                className="h-4 w-4"
              />
              Auto aperçu
            </label>
          </div>
          <div className="min-h-[520px] overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
            {previewUrl ? (
              <iframe title="Aperçu PDF" src={previewUrl} className="h-[720px] w-full" />
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-sm text-slate-500">
                {DEFAULT_PREVIEW_MESSAGE}
              </div>
            )}
          </div>
          {resolvedConfig ? (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 text-xs text-slate-400">
              <p className="font-semibold text-slate-300">Résumé actif</p>
              <p>
                Format: {resolvedConfig.format.size} • {resolvedConfig.format.orientation} • Marges{" "}
                {resolvedConfig.format.margin_preset}
              </p>
              <p>Colonnes visibles: {resolvedConfig.content.columns.filter((col) => col.visible).length}</p>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

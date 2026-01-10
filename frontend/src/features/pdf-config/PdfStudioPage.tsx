import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import {
  PdfColumnConfig,
  PdfConfig,
  PdfExportConfig,
  PdfModuleConfig,
  PdfModuleMeta,
  fetchPdfConfig,
  previewPdfConfig,
  updatePdfConfig
} from "../../lib/pdfConfig";
import { AppTextInput } from "components/AppTextInput";

const DEFAULT_PREVIEW_MESSAGE = "Utilisez le bouton Aperçu pour générer un PDF.";


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
  const { data, isFetching } = useQuery({
    queryKey: ["pdf-config"],
    queryFn: fetchPdfConfig,
    enabled: isAdmin
  });
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
    if (!data) return;
    setDraft(data);
    setInitialConfig(data);
    const moduleKeys = Object.keys(data.module_meta ?? {});
    if (moduleKeys.length > 0 && selectedModule && selectedModule !== "global") {
      if (!moduleKeys.includes(selectedModule)) {
        setSelectedModule(moduleKeys[0]);
      }
    }
    if (!selectedPreset) {
      const presets = Object.keys(data.presets ?? {});
      setSelectedPreset(presets[0] ?? null);
    }
  }, [data, selectedModule, selectedPreset]);

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

  const currentModuleMeta = selectedModule === "global" ? undefined : moduleMeta[selectedModule];
  const moduleConfig = draft?.modules[selectedModule];
  const isOverride = selectedModule !== "global" && moduleConfig?.override_global;

  const resolvedConfig = useMemo(() => {
    if (!draft) return null;
    if (selectedModule === "global") {
      return ensureColumns(cloneConfig(draft.global_config), currentModuleMeta);
    }
    const merged = resolveModuleConfig(draft, selectedModule, selectedPreset);
    return ensureColumns(merged, currentModuleMeta);
  }, [draft, selectedModule, selectedPreset, currentModuleMeta]);

  const editableConfig = useMemo(() => {
    if (!draft) return null;
    if (selectedModule === "global") {
      return ensureColumns(cloneConfig(draft.global_config), currentModuleMeta);
    }
    if (moduleConfig?.override_global) {
      return ensureColumns(cloneConfig(moduleConfig.config as PdfConfig), currentModuleMeta);
    }
    return ensureColumns(cloneConfig(draft.global_config), currentModuleMeta);
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
                <AppTextInput
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
                      <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                    <AppTextInput
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
                          <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
                  <AppTextInput
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
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">Avancé</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="space-y-1 text-sm text-slate-200">
                  Police
                  <AppTextInput
                    type="text"
                    value={editableConfig?.advanced.font_family ?? ""}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        advanced: { ...config.advanced, font_family: event.target.value }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Taille base
                  <AppTextInput
                    type="number"
                    min={8}
                    value={editableConfig?.advanced.base_font_size ?? 10}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        advanced: { ...config.advanced, base_font_size: Number(event.target.value) }
                      }))
                    }
                    className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Couleur en-tête
                  <AppTextInput
                    type="color"
                    value={editableConfig?.advanced.header_bg_color ?? "#111827"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        advanced: { ...config.advanced, header_bg_color: event.target.value }
                      }))
                    }
                    className="h-10 w-full rounded-md border border-slate-800 bg-slate-900 px-2"
                  />
                </label>
                <label className="space-y-1 text-sm text-slate-200">
                  Couleur texte en-tête
                  <AppTextInput
                    type="color"
                    value={editableConfig?.advanced.header_text_color ?? "#f8fafc"}
                    onChange={(event) =>
                      updateConfigState((config) => ({
                        ...config,
                        advanced: { ...config.advanced, header_text_color: event.target.value }
                      }))
                    }
                    className="h-10 w-full rounded-md border border-slate-800 bg-slate-900 px-2"
                  />
                </label>
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
              <AppTextInput
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

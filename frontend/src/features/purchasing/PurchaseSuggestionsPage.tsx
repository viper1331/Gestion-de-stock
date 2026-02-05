import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

type PurchaseSuggestionStatus = "draft" | "converted" | "dismissed";
type SupplierSuggestionStatus = "ok" | "missing" | "inactive" | "no_email";

interface PurchaseSuggestionLine {
  id: number;
  suggestion_id: number;
  item_id: number;
  sku: string | null;
  label: string | null;
  variant_label: string | null;
  qty_suggested: number;
  qty_final: number;
  unit: string | null;
  reason: string | null;
  reason_codes: string[];
  expiry_date: string | null;
  expiry_days_left: number | null;
  reason_label: string | null;
  stock_current: number;
  threshold: number;
}

interface PurchaseSuggestion {
  id: number;
  site_key: string;
  module_key: string;
  supplier_id: number | null;
  supplier_name: string | null;
  supplier_display: string | null;
  supplier_email: string | null;
  supplier_status: SupplierSuggestionStatus | null;
  status: PurchaseSuggestionStatus;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  lines: PurchaseSuggestionLine[];
}

interface PurchaseSuggestionUpdatePayload {
  lines: Array<{ id: number; qty_final?: number; remove?: boolean }>;
}

interface PurchaseSuggestionRefreshPayload {
  module_keys: string[];
}

interface SuggestionCardProps {
  suggestion: PurchaseSuggestion;
  moduleLabel: string;
  canEdit: boolean;
  onUpdateLines: (suggestionId: number, payload: PurchaseSuggestionUpdatePayload) => Promise<void>;
  onConvert: (suggestionId: number) => Promise<void>;
  isUpdating: boolean;
  isConverting: boolean;
}

function SuggestionCard({
  suggestion,
  moduleLabel,
  canEdit,
  onUpdateLines,
  onConvert,
  isUpdating,
  isConverting
}: SuggestionCardProps) {
  const [draftQuantities, setDraftQuantities] = useState<Record<number, number>>({});

  useEffect(() => {
    const next: Record<number, number> = {};
    suggestion.lines.forEach((line) => {
      next[line.id] = line.qty_final;
    });
    setDraftQuantities(next);
  }, [suggestion.lines]);

  const handleQuantityChange = (lineId: number, value: string) => {
    const parsed = Number(value);
    if (Number.isNaN(parsed)) {
      return;
    }
    setDraftQuantities((prev) => ({ ...prev, [lineId]: Math.max(0, Math.floor(parsed)) }));
  };

  const handleQuantityBlur = async (line: PurchaseSuggestionLine) => {
    const nextValue = draftQuantities[line.id];
    if (nextValue === undefined || nextValue === line.qty_final) {
      return;
    }
    await onUpdateLines(suggestion.id, { lines: [{ id: line.id, qty_final: nextValue }] });
  };

  const handleRemoveLine = async (lineId: number) => {
    await onUpdateLines(suggestion.id, { lines: [{ id: lineId, remove: true }] });
  };

  const hasLines = suggestion.lines.length > 0;
  const supplierStatus = suggestion.supplier_status ?? "missing";
  const hasSupplier = suggestion.supplier_id !== null;
  const supplierDisplay = hasSupplier
    ? suggestion.supplier_display ?? suggestion.supplier_name ?? "Fournisseur introuvable"
    : "Fournisseur non renseigné";
  const convertBlocked =
    !hasSupplier ||
    supplierStatus === "missing" ||
    supplierStatus === "inactive" ||
    supplierStatus === "no_email" ||
    !hasLines;
  const convertDisabled = !canEdit || isConverting || convertBlocked;
  const supplierStatusLabel = {
    missing: hasSupplier ? "Fournisseur introuvable" : "Fournisseur non renseigné",
    inactive: "Fournisseur inactif",
    no_email: "Email fournisseur manquant",
    ok: null
  } satisfies Record<SupplierSuggestionStatus, string | null>;
  const supplierStatusTooltip = {
    missing: hasSupplier
      ? "Ce fournisseur n'existe plus sur le site."
      : "Associez un fournisseur pour générer un bon de commande.",
    inactive: "Ce fournisseur est inactif ou supprimé sur le site.",
    no_email: "Ajoutez un email au fournisseur pour activer l'envoi.",
    ok: ""
  } satisfies Record<SupplierSuggestionStatus, string>;
  const convertTooltip =
    !hasSupplier
      ? "Renseignez un fournisseur pour créer un bon de commande."
      : supplierStatus === "missing"
        ? "Ce fournisseur n'existe plus sur le site."
        : supplierStatus === "inactive"
          ? "Ce fournisseur est inactif ou supprimé sur le site."
          : supplierStatus === "no_email"
            ? "Ajoutez un email fournisseur pour créer un bon de commande."
            : "";

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-white">
            {supplierDisplay ?? "Fournisseur non renseigné"}
          </h3>
          <p className="text-xs text-slate-400">
            Email : {suggestion.supplier_email ?? "—"}
          </p>
          <p className="text-xs uppercase tracking-wide text-slate-400">
            {moduleLabel} · Site {suggestion.site_key}
          </p>
          <p className="text-xs text-slate-500">
            Créée le {new Date(suggestion.created_at).toLocaleString()} · Mise à jour{" "}
            {new Date(suggestion.updated_at).toLocaleString()}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {suggestion.status === "draft" ? (
            <span className="rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
              Brouillon
            </span>
          ) : null}
          {supplierStatusLabel[supplierStatus] ? (
            <span
              className="rounded-full border border-rose-400/40 bg-rose-500/10 px-3 py-1 text-xs font-semibold text-rose-200"
              title={supplierStatusTooltip[supplierStatus]}
            >
              {supplierStatusLabel[supplierStatus]}
            </span>
          ) : null}
          {!canEdit ? (
            <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">
              Lecture seule
            </span>
          ) : null}
          <button
            type="button"
            className="rounded bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-900"
            disabled={convertDisabled}
            title={convertDisabled && convertTooltip ? convertTooltip : undefined}
            onClick={() => onConvert(suggestion.id)}
          >
            {isConverting ? "Création..." : "Créer BC"}
          </button>
        </div>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-left text-sm text-slate-200">
          <thead className="text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Article</th>
              <th className="px-3 py-2">SKU</th>
              <th className="px-3 py-2 w-32">Taille / Variante</th>
              <th className="px-3 py-2">Stock</th>
              <th className="px-3 py-2">Seuil</th>
              <th className="px-3 py-2">Qté suggérée</th>
              <th className="px-3 py-2">Qté finale</th>
              <th className="px-3 py-2">Unité</th>
              <th className="px-3 py-2">Motif</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900">
            {suggestion.lines.map((line) => (
              <tr key={line.id}>
                <td className="px-3 py-2 text-slate-100">{line.label ?? `#${line.item_id}`}</td>
                <td className="px-3 py-2 text-slate-400">{line.sku ?? "-"}</td>
                <td className="px-3 py-2 text-xs text-slate-300 md:text-sm">
                  <span className="block max-w-[140px] whitespace-normal break-words leading-snug">
                    {line.variant_label ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-400">{line.stock_current}</td>
                <td className="px-3 py-2 text-slate-400">{line.threshold}</td>
                <td className="px-3 py-2 text-slate-300">{line.qty_suggested}</td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    min={0}
                    value={draftQuantities[line.id] ?? line.qty_final}
                    onChange={(event) => handleQuantityChange(line.id, event.target.value)}
                    onBlur={() => handleQuantityBlur(line)}
                    disabled={!canEdit || isUpdating}
                    className="w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none disabled:opacity-50"
                  />
                </td>
                <td className="px-3 py-2 text-slate-400">{line.unit ?? "-"}</td>
                <td className="px-3 py-2 text-slate-500">
                  <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap gap-1">
                      {line.reason_codes.includes("EXPIRY_SOON") ? (
                        <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
                          Péremption
                        </span>
                      ) : null}
                      {line.reason_codes.includes("LOW_STOCK") ? (
                        <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-200">
                          Sous seuil
                        </span>
                      ) : null}
                    </div>
                    <span className="text-xs text-slate-400">
                      {line.reason_label ?? line.reason ?? "-"}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    className="text-xs font-semibold text-rose-300 hover:text-rose-200 disabled:cursor-not-allowed disabled:text-rose-900"
                    onClick={() => handleRemoveLine(line.id)}
                    disabled={!canEdit || isUpdating}
                  >
                    Retirer
                  </button>
                </td>
              </tr>
            ))}
            {suggestion.lines.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-center text-sm text-slate-500" colSpan={10}>
                  Aucune ligne disponible.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PurchaseSuggestionsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const clothingTitle = useModuleTitle("clothing");
  const pharmacyTitle = useModuleTitle("pharmacy");
  const remiseTitle = useModuleTitle("inventory_remise");
  const canAccessSuggestions = user?.role === "admin" || modulePermissions.canAccess("purchase_suggestions");

  const baseModuleOptions = useMemo(
    () => [
      { value: "clothing", label: clothingTitle ?? "Inventaire habillement" },
      { value: "pharmacy", label: pharmacyTitle ?? "Pharmacie" },
      { value: "inventory_remise", label: remiseTitle ?? "Inventaire remises" }
    ],
    [clothingTitle, pharmacyTitle, remiseTitle]
  );

  const visibleModules = useMemo(() => {
    if (user?.role === "admin") {
      return baseModuleOptions;
    }
    if (!canAccessSuggestions) {
      return [];
    }
    return baseModuleOptions.filter((option) => modulePermissions.canAccess(option.value));
  }, [baseModuleOptions, canAccessSuggestions, modulePermissions, user]);

  const moduleOptions = useMemo(() => {
    if (visibleModules.length <= 1) {
      return visibleModules;
    }
    return [
      { value: "all", label: "Tous les modules" },
      ...visibleModules
    ];
  }, [visibleModules]);

  const [moduleFilter, setModuleFilter] = useState<string>(() => moduleOptions[0]?.value ?? "all");
  const statusFilter: PurchaseSuggestionStatus = "draft";

  useEffect(() => {
    if (!moduleOptions.length) {
      return;
    }
    if (!moduleOptions.some((option) => option.value === moduleFilter)) {
      setModuleFilter(moduleOptions[0].value);
    }
  }, [moduleFilter, moduleOptions]);

  const canView = Boolean(canAccessSuggestions) && (user?.role === "admin" || visibleModules.length > 0);

  const { data: suggestions = [], isFetching } = useQuery({
    queryKey: ["purchase-suggestions", { status: statusFilter, module: moduleFilter }],
    queryFn: async () => {
      const response = await api.get<PurchaseSuggestion[]>("/purchasing/suggestions", {
        params: {
          status: statusFilter,
          module: moduleFilter === "all" ? undefined : moduleFilter
        }
      });
      return response.data;
    },
    enabled: canView
  });

  const refreshMutation = useMutation({
    mutationFn: async (payload: PurchaseSuggestionRefreshPayload) => {
      await api.post("/purchasing/suggestions/refresh", payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["purchase-suggestions"] });
    }
  });

  const updateLinesMutation = useMutation({
    mutationFn: async (payload: { suggestionId: number; update: PurchaseSuggestionUpdatePayload }) => {
      await api.patch(`/purchasing/suggestions/${payload.suggestionId}`, payload.update);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["purchase-suggestions"] });
    }
  });

  const convertMutation = useMutation({
    mutationFn: async (suggestionId: number) => {
      await api.post(`/purchasing/suggestions/${suggestionId}/convert`);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["purchase-suggestions"] });
    }
  });

  const refreshableModules = useMemo(() => {
    if (user?.role === "admin") {
      return visibleModules.map((module) => module.value);
    }
    return visibleModules
      .filter((module) => modulePermissions.canAccess(module.value, "edit"))
      .map((module) => module.value);
  }, [modulePermissions, user, visibleModules]);

  const canRefresh =
    refreshableModules.length > 0 &&
    (moduleFilter === "all" || refreshableModules.includes(moduleFilter));

  const handleRefresh = async () => {
    const moduleKeys =
      moduleFilter === "all"
        ? refreshableModules
        : refreshableModules.filter((module) => module === moduleFilter);
    await refreshMutation.mutateAsync({ module_keys: moduleKeys });
  };

  const handleUpdateLines = async (suggestionId: number, update: PurchaseSuggestionUpdatePayload) => {
    await updateLinesMutation.mutateAsync({ suggestionId, update });
  };

  const handleConvert = async (suggestionId: number) => {
    await convertMutation.mutateAsync(suggestionId);
  };

  const moduleLabelByKey = useMemo(() => {
    return baseModuleOptions.reduce<Record<string, string>>((acc, option) => {
      acc[option.value] = option.label;
      return acc;
    }, {});
  }, [baseModuleOptions]);

  const gateContent = (() => {
    if (modulePermissions.isPending && user?.role !== "admin") {
      return (
        <section className="space-y-4">
          <header className="space-y-1">
            <h2 className="text-2xl font-semibold text-white">Suggestions de commandes</h2>
            <p className="text-sm text-slate-400">Préparez rapidement vos bons de commande.</p>
          </header>
          <p className="text-sm text-slate-400">Vérification des permissions...</p>
        </section>
      );
    }

    if (!canView) {
      return (
        <section className="space-y-4">
          <header className="space-y-1">
            <h2 className="text-2xl font-semibold text-white">Suggestions de commandes</h2>
            <p className="text-sm text-slate-400">Préparez rapidement vos bons de commande.</p>
          </header>
          <p className="text-sm text-red-400">Accès refusé.</p>
        </section>
      );
    }

    return null;
  })();

  const blocks = useMemo<EditablePageBlock[]>(
    () => [
      {
        id: "purchase-suggestions-panel",
        title: "Suggestions de commandes",
        permissions: ["purchase_suggestions"],
        required: true,
        variant: "plain",
        defaultLayout: {
          lg: { x: 0, y: 0, w: 12, h: 16 },
          md: { x: 0, y: 0, w: 10, h: 16 },
          sm: { x: 0, y: 0, w: 6, h: 16 },
          xs: { x: 0, y: 0, w: 4, h: 16 }
        },
        render: () => (
          <EditableBlock id="purchase-suggestions-panel">
            {gateContent ? (
              gateContent
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-3">
                  <label className="text-sm font-semibold text-slate-200" htmlFor="module-filter">
                    Module
                  </label>
                  <select
                    id="module-filter"
                    value={moduleFilter}
                    onChange={(event) => setModuleFilter(event.target.value)}
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  >
                    {moduleOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="ml-auto rounded border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-200 transition hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-500"
                    onClick={handleRefresh}
                    disabled={!canRefresh || refreshMutation.isPending}
                  >
                    {refreshMutation.isPending ? "Mise à jour..." : "Rafraîchir"}
                  </button>
                  {refreshMutation.isError ? (
                    <span className="text-xs text-rose-300">Échec de la mise à jour.</span>
                  ) : null}
                </div>
                {isFetching ? (
                  <p className="text-sm text-slate-400">Chargement des suggestions...</p>
                ) : null}
                {suggestions.length === 0 && !isFetching ? (
                  <p className="text-sm text-slate-400">Aucune suggestion disponible pour le moment.</p>
                ) : null}
                <div className="space-y-4">
                  {suggestions.map((suggestion) => {
                    const moduleLabel =
                      moduleLabelByKey[suggestion.module_key] ?? suggestion.module_key;
                    const canEdit =
                      user?.role === "admin" ||
                      modulePermissions.canAccess(suggestion.module_key, "edit");
                    return (
                      <SuggestionCard
                        key={suggestion.id}
                        suggestion={suggestion}
                        moduleLabel={moduleLabel}
                        canEdit={canEdit}
                        onUpdateLines={handleUpdateLines}
                        onConvert={handleConvert}
                        isUpdating={updateLinesMutation.isPending}
                        isConverting={convertMutation.isPending}
                      />
                    );
                  })}
                </div>
              </div>
            )}
          </EditableBlock>
        )
      }
    ],
    [
      canRefresh,
      convertMutation.isPending,
      gateContent,
      handleConvert,
      handleRefresh,
      handleUpdateLines,
      isFetching,
      moduleFilter,
      moduleLabelByKey,
      moduleOptions,
      refreshMutation.isPending,
      refreshMutation.isError,
      suggestions,
      updateLinesMutation.isPending,
      user,
      modulePermissions
    ]
  );

  return (
    <EditablePageLayout
      pageKey="module:purchasing:suggestions"
      blocks={blocks}
      renderHeader={({ editButton, actionButtons, isEditing }) => (
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Suggestions de commandes</h2>
          <p className="text-sm text-slate-400">
            Analysez les articles sous seuil et transformez-les en bons de commande.
          </p>
          <div className="flex flex-wrap gap-2 pt-2">
            {editButton}
            {isEditing ? actionButtons : null}
          </div>
        </header>
      )}
    />
  );
}

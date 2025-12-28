import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ColumnManager } from "../../components/ColumnManager";
import { CustomFieldsForm } from "../../components/CustomFieldsForm";
import { api } from "../../lib/api";
import { buildCustomFieldDefaults, CustomFieldDefinition } from "../../lib/customFields";
import { persistValue, readPersistedValue } from "../../lib/persist";
import { ensureUniqueSku, normalizeSkuInput, type ExistingSkuEntry } from "../../lib/sku";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { PharmacyOrdersPanel } from "./PharmacyOrdersPanel";
import { PharmacyLotsPanel } from "./PharmacyLotsPanel";
import { useModuleTitle } from "../../lib/moduleTitles";

const DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD = 5;

interface PharmacyItem {
  id: number;
  name: string;
  dosage: string | null;
  packaging: string | null;
  barcode: string | null;
  quantity: number;
  low_stock_threshold: number;
  expiration_date: string | null;
  location: string | null;
  category_id: number | null;
  extra?: Record<string, unknown>;
}

interface PharmacyPayload {
  name: string;
  dosage: string | null;
  packaging: string | null;
  barcode: string | null;
  quantity: number;
  low_stock_threshold: number;
  expiration_date: string | null;
  location: string | null;
  category_id: number | null;
  extra: Record<string, unknown>;
}

const EMPTY_PHARMACY_PAYLOAD: PharmacyPayload = {
  name: "",
  dosage: null,
  packaging: null,
  barcode: null,
  quantity: 0,
  low_stock_threshold: DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD,
  expiration_date: null,
  location: null,
  category_id: null,
  extra: {}
};

interface PharmacyFormDraft {
  name: string;
  dosage: string;
  packaging: string;
  barcode: string;
  quantity: number;
  low_stock_threshold: number;
  expiration_date: string;
  location: string;
  category_id: string;
  extra: Record<string, unknown>;
}

function createPharmacyFormDraft(payload: PharmacyPayload): PharmacyFormDraft {
  return {
    name: payload.name ?? "",
    dosage: payload.dosage ?? "",
    packaging: payload.packaging ?? "",
    barcode: payload.barcode ?? "",
    quantity: payload.quantity ?? 0,
    low_stock_threshold:
      payload.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD,
    expiration_date: payload.expiration_date ?? "",
    location: payload.location ?? "",
    category_id: payload.category_id ? String(payload.category_id) : "",
    extra: payload.extra ?? {}
  };
}

interface PharmacyCategory {
  id: number;
  name: string;
  sizes: string[];
}

interface PharmacyMovement {
  id: number;
  pharmacy_item_id: number;
  delta: number;
  reason: string | null;
  created_at: string;
}

interface PharmacyMovementPayload {
  delta: number;
  reason: string | null;
}

type PharmacyColumnKey =
  | "name"
  | "barcode"
  | "dosage"
  | "packaging"
  | "quantity"
  | "low_stock_threshold"
  | "expiration"
  | "location"
  | "category";

const PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY = "gsp/pharmacy-column-visibility";

const DEFAULT_PHARMACY_COLUMN_VISIBILITY: Record<PharmacyColumnKey, boolean> = {
  name: true,
  barcode: true,
  dosage: true,
  packaging: true,
  quantity: true,
  low_stock_threshold: true,
  expiration: true,
  location: true,
  category: false
};

const PHARMACY_COLUMN_OPTIONS: { key: PharmacyColumnKey; label: string }[] = [
  { key: "name", label: "Nom" },
  { key: "barcode", label: "Code-barres" },
  { key: "dosage", label: "Dosage" },
  { key: "packaging", label: "Conditionnement" },
  { key: "quantity", label: "Quantité" },
  { key: "low_stock_threshold", label: "Seuil faible" },
  { key: "expiration", label: "Expiration" },
  { key: "location", label: "Localisation" },
  { key: "category", label: "Catégorie" }
];

export function PharmacyPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PharmacyItem | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [isFormVisible, setIsFormVisible] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [movementItemId, setMovementItemId] = useState<number | null>(null);

  const [columnVisibility, setColumnVisibility] = useState<Record<PharmacyColumnKey, boolean>>(() => ({
    ...readPersistedValue<Record<PharmacyColumnKey, boolean>>(
      PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY,
      DEFAULT_PHARMACY_COLUMN_VISIBILITY
    )
  }));

  const toggleColumnVisibility = (key: PharmacyColumnKey) => {
    setColumnVisibility((previous) => {
      const isCurrentlyVisible = previous[key] !== false;
      if (isCurrentlyVisible) {
        const visibleCount = Object.values(previous).filter(Boolean).length;
        if (visibleCount <= 1) {
          return previous;
        }
      }
      const next = { ...previous, [key]: !isCurrentlyVisible } as Record<PharmacyColumnKey, boolean>;
      persistValue(PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY, next);
      return next;
    });
  };

  const resetColumnVisibility = () => {
    const next = { ...DEFAULT_PHARMACY_COLUMN_VISIBILITY };
    setColumnVisibility(next);
    persistValue(PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY, next);
  };

  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("pharmacy");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("pharmacy", "edit");
  const moduleTitle = useModuleTitle("pharmacy");

  const { data: items = [], isFetching } = useQuery({
    queryKey: ["pharmacy"],
    queryFn: async () => {
      const response = await api.get<PharmacyItem[]>("/pharmacy/");
      return response.data;
    },
    enabled: canView
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["pharmacy-categories"],
    queryFn: async () => {
      const response = await api.get<PharmacyCategory[]>("/pharmacy/categories/");
      return response.data;
    },
    enabled: canView
  });

  const { data: customFieldDefinitions = [] } = useQuery({
    queryKey: ["custom-fields", "pharmacy_items"],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: "pharmacy_items" }
      });
      return response.data;
    },
    enabled: user?.role === "admin"
  });
  const activeCustomFields = useMemo(
    () => customFieldDefinitions.filter((definition) => definition.is_active),
    [customFieldDefinitions]
  );

  const existingBarcodes = useMemo<ExistingSkuEntry[]>(
    () =>
      items
        .filter((item) => item.barcode && item.barcode.trim().length > 0)
        .map((item) => ({ id: item.id, sku: item.barcode as string })),
    [items]
  );

  useEffect(() => {
    if (movementItemId === null) {
      return;
    }
    if (!items.some((item) => item.id === movementItemId)) {
      setMovementItemId(null);
    }
  }, [items, movementItemId]);

  const categoryNames = useMemo(() => new Map(categories.map((category) => [category.id, category.name])), [categories]);
  const selectedMovementItem = useMemo(
    () => (movementItemId === null ? null : items.find((item) => item.id === movementItemId) ?? null),
    [items, movementItemId]
  );

  const createItem = useMutation({
    mutationFn: async (payload: PharmacyPayload) => {
      await api.post("/pharmacy/", payload);
    },
    onSuccess: async () => {
      setMessage("Médicament créé.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de créer l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateItem = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: PharmacyPayload }) => {
      await api.put(`/pharmacy/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Médicament mis à jour.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de mettre à jour l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteItem = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/pharmacy/${id}`);
    },
    onSuccess: async () => {
      setMessage("Médicament supprimé.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de supprimer l'élément."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const recordMovement = useMutation({
    mutationFn: async ({ itemId, payload }: { itemId: number; payload: PharmacyMovementPayload }) => {
      await api.post(`/pharmacy/${itemId}/movements`, payload);
    },
    onSuccess: async (_, variables) => {
      setMessage("Mouvement enregistré.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-movements", variables.itemId] });
    },
    onError: () => setError("Impossible d'enregistrer le mouvement."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const createCategory = useMutation({
    mutationFn: async (payload: { name: string; sizes: string[] }) => {
      await api.post("/pharmacy/categories/", payload);
    },
    onSuccess: async () => {
      setMessage("Catégorie créée.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-categories"] });
    },
    onError: () => setError("Impossible de créer la catégorie."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateCategory = useMutation({
    mutationFn: async ({ categoryId, payload }: { categoryId: number; payload: { sizes: string[] } }) => {
      await api.put(`/pharmacy/categories/${categoryId}`, payload);
    },
    onSuccess: async () => {
      setMessage("Catégorie mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-categories"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de mettre à jour la catégorie."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteCategory = useMutation({
    mutationFn: async (categoryId: number) => {
      await api.delete(`/pharmacy/categories/${categoryId}`);
    },
    onSuccess: async () => {
      setMessage("Catégorie supprimée.");
      await queryClient.invalidateQueries({ queryKey: ["pharmacy-categories"] });
      await queryClient.invalidateQueries({ queryKey: ["pharmacy"] });
    },
    onError: () => setError("Impossible de supprimer la catégorie."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const apiBaseUrl = (api.defaults.baseURL ?? "").replace(/\/$/, "");

  const formValues = useMemo<PharmacyPayload>(() => {
    const extraDefaults = buildCustomFieldDefaults(activeCustomFields, selected?.extra ?? {});
    if (formMode === "edit" && selected) {
      return {
        name: selected.name,
        dosage: selected.dosage,
        packaging: selected.packaging,
        barcode: selected.barcode,
        quantity: selected.quantity,
        low_stock_threshold: selected.low_stock_threshold,
        expiration_date: selected.expiration_date,
        location: selected.location,
        category_id: selected.category_id,
        extra: extraDefaults
      };
    }
    return { ...EMPTY_PHARMACY_PAYLOAD, extra: buildCustomFieldDefaults(activeCustomFields, {}) };
  }, [activeCustomFields, formMode, selected]);

  const [draft, setDraft] = useState<PharmacyFormDraft>(() => createPharmacyFormDraft(formValues));
  const [isBarcodeAuto, setIsBarcodeAuto] = useState<boolean>(
    !(formValues.barcode && formValues.barcode.trim().length > 0)
  );

  useEffect(() => {
    setDraft(createPharmacyFormDraft(formValues));
    setIsBarcodeAuto(!(formValues.barcode && formValues.barcode.trim().length > 0));
  }, [formValues]);

  const buildBarcodeSource = (data: PharmacyFormDraft) =>
    [data.name, data.dosage, data.packaging]
      .map((value) => value.trim())
      .filter((value) => value.length > 0)
      .join(" ");

  const regenerateBarcodeIfNeeded = (data: PharmacyFormDraft): string => {
    if (!isBarcodeAuto) {
      return data.barcode;
    }
    return ensureUniqueSku({
      desiredSku: "",
      prefix: "PHA",
      source: buildBarcodeSource(data),
      existingSkus: existingBarcodes,
      excludeId: formMode === "edit" && selected ? selected.id ?? null : null
    });
  };

  const updateDraft = (updates: Partial<PharmacyFormDraft>, regenerate = false) => {
    setDraft((previous) => {
      const next = { ...previous, ...updates };
      if (regenerate) {
        next.barcode = regenerateBarcodeIfNeeded(next);
      }
      return next;
    });
  };

  const handleBarcodeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const normalized = normalizeSkuInput(event.target.value);
    setDraft((previous) => ({ ...previous, barcode: normalized }));
    setIsBarcodeAuto(normalized.length === 0);
  };

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Suivi des stocks pharmaceutiques.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Suivi des stocks pharmaceutiques.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = draft.name.trim();
    if (!trimmedName) {
      setError("Le nom est obligatoire.");
      return;
    }

    const normalizedQuantity = Number.isNaN(draft.quantity) ? 0 : draft.quantity;
    if (normalizedQuantity < 0) {
      setError("La quantité doit être positive.");
      return;
    }

    const normalizedThreshold = Number.isNaN(draft.low_stock_threshold)
      ? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD
      : draft.low_stock_threshold;
    if (normalizedThreshold < 0) {
      setError("Le seuil de stock doit être positif ou nul.");
      return;
    }

    const finalBarcode = ensureUniqueSku({
      desiredSku: draft.barcode,
      prefix: "PHA",
      source: buildBarcodeSource(draft),
      existingSkus: existingBarcodes,
      excludeId: formMode === "edit" && selected ? selected.id ?? null : null
    });

    const payload: PharmacyPayload = {
      name: trimmedName,
      dosage: draft.dosage.trim() ? draft.dosage.trim() : null,
      packaging: draft.packaging.trim() ? draft.packaging.trim() : null,
      barcode: finalBarcode,
      quantity: normalizedQuantity,
      low_stock_threshold: normalizedThreshold,
      expiration_date: draft.expiration_date.trim() ? draft.expiration_date : null,
      location: draft.location.trim() ? draft.location.trim() : null,
      category_id: draft.category_id.trim() ? Number(draft.category_id) : null,
      extra: draft.extra
    };

    setDraft((previous) => ({ ...previous, barcode: finalBarcode }));
    setMessage(null);
    setError(null);

    if (formMode === "edit" && selected) {
      await updateItem.mutateAsync({ id: selected.id, payload });
    } else {
      await createItem.mutateAsync(payload);
      setDraft(
        createPharmacyFormDraft({
          ...EMPTY_PHARMACY_PAYLOAD,
          extra: buildCustomFieldDefaults(activeCustomFields, {})
        })
      );
      setIsBarcodeAuto(true);
    }
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gérez vos médicaments et consommables médicaux.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ColumnManager
            options={PHARMACY_COLUMN_OPTIONS}
            visibility={columnVisibility}
            onToggle={(key) => toggleColumnVisibility(key as PharmacyColumnKey)}
            onReset={resetColumnVisibility}
            description="Personnalisez les colonnes visibles dans le tableau."
          />
          {canEdit ? (
            <button
              type="button"
              onClick={() => {
                setSelected(null);
                setFormMode("create");
                setIsFormVisible(true);
              }}
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
              title="Créer une nouvelle référence pharmaceutique"
            >
              Nouvel article
            </button>
          ) : null}
        </div>
      </header>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className={`grid gap-6 ${isFormVisible && canEdit ? "lg:grid-cols-3" : ""}`}>
        <div className={isFormVisible && canEdit ? "lg:col-span-2" : ""}>
          <div
            className="max-h-[520px] overflow-y-auto rounded-lg border border-slate-800"
            style={{ maxHeight: "calc(8 * 56px + 48px)" }}
          >
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  {columnVisibility.name !== false ? <th className="px-4 py-3 text-left">Nom</th> : null}
                  {columnVisibility.barcode !== false ? <th className="px-4 py-3 text-left">Code-barres</th> : null}
                  {columnVisibility.dosage !== false ? <th className="px-4 py-3 text-left">Dosage</th> : null}
                  {columnVisibility.packaging !== false ? <th className="px-4 py-3 text-left">Conditionnement</th> : null}
                  {columnVisibility.quantity !== false ? <th className="px-4 py-3 text-left">Quantité</th> : null}
                  {columnVisibility.low_stock_threshold !== false ? (
                    <th className="px-4 py-3 text-left">Seuil faible</th>
                  ) : null}
                  {columnVisibility.expiration !== false ? <th className="px-4 py-3 text-left">Expiration</th> : null}
                  {columnVisibility.location !== false ? <th className="px-4 py-3 text-left">Localisation</th> : null}
                  {columnVisibility.category !== false ? <th className="px-4 py-3 text-left">Catégorie</th> : null}
                  {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {items.map((item) => {
                  const { isOutOfStock, isLowStock, expirationStatus } = getPharmacyAlerts(item);
                  const barcodeDownloadUrl = item.barcode
                    ? `${apiBaseUrl}/barcode/generate/${encodeURIComponent(item.barcode)}`
                    : null;
                  return (
                    <tr
                      key={item.id}
                      className={`bg-slate-950 text-sm text-slate-100 ${
                        selected?.id === item.id && formMode === "edit" ? "ring-1 ring-indigo-500" : ""
                      }`}
                    >
                      {columnVisibility.name !== false ? (
                        <td className="px-4 py-3 font-medium">{item.name}</td>
                      ) : null}
                      {columnVisibility.barcode !== false ? (
                        <td className="px-4 py-3 text-slate-300">
                          {item.barcode ? (
                            <div className="flex items-center gap-2">
                              <code className="rounded bg-slate-900 px-2 py-1 text-xs text-slate-100">{item.barcode}</code>
                              {barcodeDownloadUrl ? (
                                <a
                                  href={barcodeDownloadUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-[10px] font-semibold uppercase tracking-wide text-indigo-300 hover:text-indigo-200"
                                  title="Télécharger le code-barres (PNG)"
                                >
                                  PNG
                                </a>
                              ) : null}
                            </div>
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                      ) : null}
                      {columnVisibility.dosage !== false ? (
                        <td className="px-4 py-3 text-slate-300">{item.dosage ?? "-"}</td>
                      ) : null}
                      {columnVisibility.packaging !== false ? (
                        <td className="px-4 py-3 text-slate-300">{item.packaging ?? "-"}</td>
                      ) : null}
                      {columnVisibility.quantity !== false ? (
                        <td className="px-4 py-3 font-semibold">
                          {item.quantity}
                          {isOutOfStock ? (
                            <span className="ml-2 inline-flex items-center rounded border border-red-500/40 bg-red-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-200">
                              Rupture
                            </span>
                          ) : isLowStock ? (
                            <span className="ml-2 inline-flex items-center rounded border border-amber-500/40 bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
                              Faible stock
                            </span>
                          ) : null}
                        </td>
                      ) : null}
                      {columnVisibility.low_stock_threshold !== false ? (
                        <td className="px-4 py-3 text-slate-300">
                          {item.low_stock_threshold > 0 ? item.low_stock_threshold : "-"}
                        </td>
                      ) : null}
                      {columnVisibility.expiration !== false ? (
                        <td
                          className={`px-4 py-3 ${
                            expirationStatus === "expired"
                              ? "text-red-300"
                              : expirationStatus === "expiring-soon"
                                ? "text-amber-200"
                                : "text-slate-300"
                          }`}
                        >
                          {formatDate(item.expiration_date)}
                          {expirationStatus === "expired" ? (
                            <span className="ml-2 inline-flex items-center rounded border border-red-500/40 bg-red-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-300">
                              Expiré
                            </span>
                          ) : null}
                          {expirationStatus === "expiring-soon" ? (
                            <span className="ml-2 inline-flex items-center rounded border border-orange-400/40 bg-orange-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-orange-200">
                              Bientôt périmé
                            </span>
                          ) : null}
                        </td>
                      ) : null}
                      {columnVisibility.location !== false ? (
                        <td className="px-4 py-3 text-slate-300">{item.location ?? "-"}</td>
                      ) : null}
                      {columnVisibility.category !== false ? (
                        <td className="px-4 py-3 text-slate-300">
                          {item.category_id ? categoryNames.get(item.category_id) ?? "-" : "-"}
                        </td>
                      ) : null}
                      {canEdit ? (
                        <td className="px-4 py-3 text-xs text-slate-200">
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setSelected(item);
                                setFormMode("edit");
                                setIsFormVisible(true);
                              }}
                              className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                              title={`Modifier la fiche de ${item.name}`}
                            >
                              Modifier
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setMovementItemId(item.id);
                              }}
                              className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                              title={`Enregistrer un mouvement pour ${item.name}`}
                            >
                              Mouvement
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (!window.confirm("Supprimer cet article pharmaceutique ?")) {
                                  return;
                                }
                                setMessage(null);
                                setError(null);
                                void deleteItem.mutateAsync(item.id);
                              }}
                              className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                              title={`Supprimer ${item.name} de la pharmacie`}
                            >
                              Supprimer
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {isFetching ? <p className="mt-2 text-xs text-slate-400">Actualisation...</p> : null}
        </div>

        {canEdit && isFormVisible ? (
          <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-white">
                {formMode === "edit" ? "Modifier l'article" : "Ajouter un article"}
              </h3>
              <button
                type="button"
                onClick={() => setIsFormVisible((previous) => !previous)}
                className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
                title={isFormVisible ? "Masquer le formulaire" : "Afficher le formulaire"}
              >
                {isFormVisible ? "Fermer" : "Ouvrir"}
              </button>
            </div>
            {isFormVisible ? (
              <form
                key={`${formMode}-${selected?.id ?? "new"}`}
                className="mt-3 space-y-3"
                onSubmit={handleSubmit}
              >
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-name">
                    Nom
                  </label>
                  <input
                    id="pharmacy-name"
                    value={draft.name}
                    onChange={(event) => updateDraft({ name: event.target.value }, true)}
                    required
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Nom du médicament ou du consommable"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-dosage">
                    Dosage
                  </label>
                  <input
                    id="pharmacy-dosage"
                    value={draft.dosage}
                    onChange={(event) => updateDraft({ dosage: event.target.value }, true)}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Dosage ou concentration si applicable"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-packaging">
                    Conditionnement
                  </label>
                  <input
                    id="pharmacy-packaging"
                    value={draft.packaging}
                    onChange={(event) => updateDraft({ packaging: event.target.value }, true)}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Conditionnement de l'article (boîte, unité...)"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-barcode">
                    Code-barres
                  </label>
                  <input
                    id="pharmacy-barcode"
                    value={draft.barcode}
                    onChange={handleBarcodeChange}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Code-barres associé (facultatif)"
                    inputMode="text"
                    pattern="[\x20-\x7E]*"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-category">
                    Catégorie
                  </label>
                  <select
                    id="pharmacy-category"
                    value={draft.category_id}
                    onChange={(event) => updateDraft({ category_id: event.target.value })}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Associez ce produit à une catégorie métier"
                  >
                    <option value="">Aucune</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-quantity">
                    Quantité
                  </label>
                  <input
                    id="pharmacy-quantity"
                    type="number"
                    min={0}
                    value={Number.isNaN(draft.quantity) ? "" : draft.quantity}
                    onChange={(event) => {
                      const { value } = event.target;
                      updateDraft(
                        { quantity: value === "" ? Number.NaN : Number(value) },
                        false
                      );
                    }}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    required
                    title="Quantité disponible en stock"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-low-stock-threshold">
                    Seuil de stock faible
                  </label>
                  <input
                    id="pharmacy-low-stock-threshold"
                    type="number"
                    min={0}
                    value={
                      Number.isNaN(draft.low_stock_threshold) ? "" : draft.low_stock_threshold
                    }
                    onChange={(event) => {
                      const { value } = event.target;
                      updateDraft(
                        {
                          low_stock_threshold:
                            value === "" ? Number.NaN : Number(value)
                        },
                        false
                      );
                    }}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    required
                    title="Quantité minimale avant alerte de stock faible"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-expiration">
                    Date d'expiration
                  </label>
                  <input
                    id="pharmacy-expiration"
                    type="date"
                    value={draft.expiration_date}
                    onChange={(event) => updateDraft({ expiration_date: event.target.value })}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Date d'expiration (facultative)"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-location">
                    Localisation
                  </label>
                  <input
                    id="pharmacy-location"
                    value={draft.location}
                    onChange={(event) => updateDraft({ location: event.target.value })}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Emplacement de stockage (armoire, pièce...)"
                  />
                </div>
                {activeCustomFields.length > 0 ? (
                  <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Champs personnalisés
                    </p>
                    <div className="mt-3">
                      <CustomFieldsForm
                        definitions={activeCustomFields}
                        values={draft.extra}
                        onChange={(next) => updateDraft({ extra: next })}
                        disabled={createItem.isPending || updateItem.isPending}
                      />
                    </div>
                  </div>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={createItem.isPending || updateItem.isPending}
                    className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    title={
                      formMode === "edit"
                        ? "Enregistrer les modifications du médicament"
                        : "Ajouter ce médicament au stock"
                    }
                  >
                    {formMode === "edit"
                      ? updateItem.isPending
                        ? "Mise à jour..."
                        : "Enregistrer"
                      : createItem.isPending
                        ? "Ajout..."
                        : "Ajouter"}
                  </button>
                  {formMode === "edit" ? (
                    <button
                      type="button"
                      onClick={() => {
                        setSelected(null);
                        setFormMode("create");
                      }}
                      className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                      title="Annuler la modification en cours"
                    >
                      Annuler
                    </button>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="mt-3 text-xs text-slate-400">
                Formulaire masqué. Cliquez sur « Ouvrir » pour ajouter ou modifier un article.
              </p>
            )}
            <div className="mt-6 space-y-4">
              <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <h4 className="text-sm font-semibold text-white">Mouvement de stock</h4>
                <PharmacyMovementForm
                  items={items}
                  selectedItemId={movementItemId}
                  onSelectItem={setMovementItemId}
                  onSubmit={async (values) => {
                    if (movementItemId === null) {
                      return;
                    }
                    setError(null);
                    await recordMovement.mutateAsync({ itemId: movementItemId, payload: values });
                  }}
                  isSubmitting={recordMovement.isPending}
                />
                <PharmacyMovementHistory item={selectedMovementItem} />
              </section>
              <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <h4 className="text-sm font-semibold text-white">Catégories</h4>
                <p className="text-xs text-slate-400">
                  Organisez vos références par familles pour faciliter les recherches et analyses.
                </p>
                <PharmacyCategoryManager
                  categories={categories}
                  onCreate={async (values) => {
                    setError(null);
                    await createCategory.mutateAsync(values);
                  }}
                  onDelete={async (categoryId) => {
                    if (!window.confirm("Supprimer cette catégorie ?")) {
                      return;
                    }
                    setError(null);
                    await deleteCategory.mutateAsync(categoryId);
                  }}
                  onUpdate={async (categoryId, payload) => {
                    setError(null);
                    await updateCategory.mutateAsync({ categoryId, payload });
                  }}
                  isSubmitting={
                    createCategory.isPending || updateCategory.isPending || deleteCategory.isPending
                  }
                />
              </section>
            </div>
          </aside>
        ) : null}
      </div>

      <PharmacyLotsPanel canEdit={canEdit} />
      <PharmacyOrdersPanel canEdit={canEdit} />
    </section>
  );
}

function PharmacyMovementForm({
  items,
  selectedItemId,
  onSelectItem,
  onSubmit,
  isSubmitting
}: {
  items: PharmacyItem[];
  selectedItemId: number | null;
  onSelectItem: (itemId: number | null) => void;
  onSubmit: (payload: PharmacyMovementPayload) => Promise<void>;
  isSubmitting: boolean;
}) {
  const [delta, setDelta] = useState(1);
  const [reason, setReason] = useState("");

  useEffect(() => {
    setDelta(1);
    setReason("");
  }, [selectedItemId]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selectedItemId === null) {
      return;
    }
    await onSubmit({ delta, reason: reason.trim() ? reason.trim() : null });
    setDelta(1);
    setReason("");
  };

  return (
    <form className="mt-3 space-y-3" onSubmit={handleSubmit}>
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-movement-item">
          Article concerné
        </label>
        <select
          id="pharmacy-movement-item"
          value={selectedItemId ?? ""}
          onChange={(event) => {
            const value = event.target.value ? Number(event.target.value) : null;
            onSelectItem(value);
          }}
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title="Choisissez l'article à ajuster"
        >
          <option value="">Sélectionnez un article</option>
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-3">
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-movement-delta">
            Variation
          </label>
          <input
            id="pharmacy-movement-delta"
            type="number"
            value={delta}
            onChange={(event) => setDelta(Number(event.target.value))}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Valeur positive ou négative à appliquer"
          />
        </div>
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-movement-reason">
            Motif
          </label>
          <input
            id="pharmacy-movement-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            placeholder="Inventaire, casse..."
            title="Précisez la raison du mouvement"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={selectedItemId === null || isSubmitting}
        className="w-full rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
        title={selectedItemId === null ? "Sélectionnez un article" : "Valider ce mouvement"}
      >
        {isSubmitting ? "Enregistrement..." : "Valider le mouvement"}
      </button>
    </form>
  );
}

function PharmacyMovementHistory({ item }: { item: PharmacyItem | null }) {
  const { data: movements = [], isFetching } = useQuery({
    queryKey: ["pharmacy-movements", item?.id ?? "none"],
    queryFn: async () => {
      if (!item) {
        return [] as PharmacyMovement[];
      }
      const response = await api.get<PharmacyMovement[]>(`/pharmacy/${item.id}/movements`);
      return response.data;
    },
    enabled: Boolean(item),
    placeholderData: [] as PharmacyMovement[]
  });

  if (!item) {
    return <p className="mt-3 text-xs text-slate-400">Sélectionnez un article pour consulter l'historique.</p>;
  }

  return (
    <div className="mt-4 space-y-2">
      <h5 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Derniers mouvements</h5>
      {isFetching ? <p className="text-xs text-slate-500">Chargement...</p> : null}
      <ul className="space-y-2 text-xs text-slate-200">
        {movements.length === 0 ? <li className="text-slate-500">Aucun mouvement enregistré.</li> : null}
        {movements.slice(0, 6).map((movement) => (
          <li key={movement.id} className="rounded border border-slate-800 bg-slate-900/70 p-2">
            <div className="flex items-center justify-between">
              <span
                className={`font-semibold ${movement.delta >= 0 ? "text-emerald-300" : "text-red-300"}`}
              >
                {movement.delta >= 0 ? `+${movement.delta}` : movement.delta}
              </span>
              <span className="text-[10px] text-slate-400">{formatMovementDate(movement.created_at)}</span>
            </div>
            {movement.reason ? (
              <p className="mt-1 text-[11px] text-slate-300">{movement.reason}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PharmacyCategoryManager({
  categories,
  onCreate,
  onDelete,
  onUpdate,
  isSubmitting
}: {
  categories: PharmacyCategory[];
  onCreate: (values: { name: string; sizes: string[] }) => Promise<void>;
  onDelete: (categoryId: number) => Promise<void>;
  onUpdate: (categoryId: number, payload: { sizes: string[] }) => Promise<void>;
  isSubmitting: boolean;
}) {
  const [name, setName] = useState("");
  const [sizes, setSizes] = useState("");
  const [editedSizes, setEditedSizes] = useState<Record<number, string>>({});

  useEffect(() => {
    setEditedSizes((previous) => {
      const next: Record<number, string> = {};
      for (const category of categories) {
        next[category.id] = previous[category.id] ?? category.sizes.join(", ");
      }
      return next;
    });
  }, [categories]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    const parsedSizes = parseSizesInput(sizes);
    await onCreate({ name: trimmed, sizes: parsedSizes });
    setName("");
    setSizes("");
  };

  const handleSave = async (categoryId: number) => {
    const rawValue = editedSizes[categoryId] ?? "";
    const parsedSizes = parseSizesInput(rawValue);
    await onUpdate(categoryId, { sizes: parsedSizes });
    setEditedSizes((previous) => ({ ...previous, [categoryId]: parsedSizes.join(", ") }));
  };

  return (
    <div className="mt-3 space-y-3">
      <form className="space-y-2" onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nouvelle catégorie"
            className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Nom de la catégorie"
          />
          <input
            value={sizes}
            onChange={(event) => setSizes(event.target.value)}
            placeholder="Tailles ou formats"
            className="w-56 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Valeurs séparées par des virgules"
          />
        </div>
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSubmitting ? "Traitement..." : "Ajouter"}
        </button>
      </form>
      <ul className="space-y-3 text-xs text-slate-100">
        {categories.length === 0 ? (
          <li className="text-slate-500">Aucune catégorie enregistrée.</li>
        ) : null}
        {categories.map((category) => (
          <li key={category.id} className="rounded border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-white">{category.name}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void handleSave(category.id)}
                  className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-800"
                  disabled={isSubmitting}
                >
                  Enregistrer
                </button>
                <button
                  type="button"
                  onClick={() => void onDelete(category.id)}
                  className="rounded bg-red-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-red-500"
                  disabled={isSubmitting}
                >
                  Supprimer
                </button>
              </div>
            </div>
            <label className="mt-2 block text-[11px] font-semibold uppercase tracking-wide text-slate-400" htmlFor={`category-sizes-${category.id}`}>
              Tailles / formats
            </label>
            <input
              id={`category-sizes-${category.id}`}
              value={editedSizes[category.id] ?? category.sizes.join(", ")}
              onChange={(event) =>
                setEditedSizes((previous) => ({ ...previous, [category.id]: event.target.value }))
              }
              className="mt-1 w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-[11px] text-slate-100 focus:border-indigo-500 focus:outline-none"
              placeholder="Saisir des valeurs séparées par des virgules"
              title="Modifiez la liste des tailles ou conditionnements"
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function parseSizesInput(value: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of value.split(",")) {
    const trimmed = part.trim();
    if (!trimmed) {
      continue;
    }
    const key = trimmed.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(trimmed);
  }
  return result;
}

function formatMovementDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: "short"
    }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

type ExpirationStatus = "expired" | "expiring-soon" | null;

function getPharmacyAlerts(item: PharmacyItem) {
  const isOutOfStock = item.quantity <= 0;
  const threshold = item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD;
  const hasThreshold = threshold > 0;
  const isLowStock = !isOutOfStock && hasThreshold && item.quantity <= threshold;
  const expirationStatus = getExpirationStatus(item.expiration_date);

  return { isOutOfStock, isLowStock, expirationStatus };
}

function getExpirationStatus(value: string | null): ExpirationStatus {
  if (!value) {
    return null;
  }

  const expirationDate = new Date(value);
  if (Number.isNaN(expirationDate.getTime())) {
    return null;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const expiration = new Date(expirationDate);
  expiration.setHours(0, 0, 0, 0);

  const diffInMs = expiration.getTime() - today.getTime();
  const diffInDays = Math.floor(diffInMs / (1000 * 60 * 60 * 24));

  if (diffInDays < 0) {
    return "expired";
  }

  if (diffInDays <= 30) {
    return "expiring-soon";
  }

  return null;
}

import { ChangeEvent, FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { ColumnManager } from "../../components/ColumnManager";
import { CustomFieldsForm } from "../../components/CustomFieldsForm";
import { api } from "../../lib/api";
import { buildCustomFieldDefaults, CustomFieldDefinition, sortCustomFields } from "../../lib/customFields";
import { persistValue, readPersistedValue } from "../../lib/persist";
import { ensureUniqueSku, normalizeSkuInput, type ExistingSkuEntry } from "../../lib/sku";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { PharmacyOrdersPanel } from "./PharmacyOrdersPanel";
import { PharmacyLotsPanel } from "./PharmacyLotsPanel";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

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
  supplier_id: number | null;
  supplier_name?: string | null;
  supplier_email?: string | null;
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
  supplier_id: number | null;
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
  supplier_id: null,
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
  supplier_id: string;
  extra: Record<string, unknown>;
}

interface SupplierOption {
  id: number;
  name: string;
  email: string | null;
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
    supplier_id: payload.supplier_id ? String(payload.supplier_id) : "",
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
  | "category"
  | "supplier";

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
  category: false,
  supplier: true
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
  { key: "category", label: "Catégorie" },
  { key: "supplier", label: "Fournisseur" }
];

const normalizeSearchTerm = (value: string) => value.toLowerCase().replace(/\s+/g, " ").trim();

const highlightMatch = (value: string, term: string) => {
  if (!term) {
    return value;
  }
  const lowerValue = value.toLowerCase();
  const lowerTerm = term.toLowerCase();
  const startIndex = lowerValue.indexOf(lowerTerm);
  if (startIndex === -1) {
    return value;
  }
  const endIndex = startIndex + lowerTerm.length;
  const mainContent = (
    <>
      {value.slice(0, startIndex)}
      <span className="rounded bg-indigo-500/20 px-1 text-indigo-100">{value.slice(startIndex, endIndex)}</span>
      {value.slice(endIndex)}
    </>
  );
  return mainContent;
};

export function PharmacyPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PharmacyItem | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [isFormVisible, setIsFormVisible] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [movementItemId, setMovementItemId] = useState<number | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const [tableMaxHeight, setTableMaxHeight] = useState<number | null>(null);

  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() => ({
    ...DEFAULT_PHARMACY_COLUMN_VISIBILITY,
    ...readPersistedValue<Record<string, boolean>>(
      PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY,
      DEFAULT_PHARMACY_COLUMN_VISIBILITY
    )
  }));

  const toggleColumnVisibility = (key: string, optionKeys: Set<string>) => {
    setColumnVisibility((previous) => {
      const isCurrentlyVisible = previous[key] !== false;
      if (isCurrentlyVisible) {
        const visibleCount = Array.from(optionKeys).filter(
          (optionKey) => previous[optionKey] !== false
        ).length;
        if (visibleCount <= 1) {
          return previous;
        }
      }
      const next = { ...previous, [key]: !isCurrentlyVisible };
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
  const canViewSuppliers = user?.role === "admin" || modulePermissions.canAccess("suppliers");
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

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers", { module: "pharmacy" }],
    queryFn: async () => {
      const response = await api.get<SupplierOption[]>("/suppliers/", {
        params: { module: "pharmacy" }
      });
      return response.data;
    },
    enabled: canView && canViewSuppliers
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
  const customColumns = useMemo(
    () =>
      sortCustomFields(activeCustomFields).map((definition) => ({
        key: `custom:${definition.id}`,
        label: definition.label,
        fieldKey: definition.key
      })),
    [activeCustomFields]
  );
  const columnOptions = useMemo(
    () => [
      ...PHARMACY_COLUMN_OPTIONS.map((option) => ({ ...option, kind: "native" as const })),
      ...customColumns.map((column) => ({
        key: column.key,
        label: column.label,
        kind: "custom" as const
      }))
    ],
    [customColumns]
  );
  const columnOptionKeys = useMemo(() => new Set(columnOptions.map((option) => option.key)), [columnOptions]);
  useEffect(() => {
    setColumnVisibility((previous) => {
      const next: Record<string, boolean> = {};
      for (const option of columnOptions) {
        if (previous[option.key] !== undefined) {
          next[option.key] = previous[option.key];
        } else if (option.key in DEFAULT_PHARMACY_COLUMN_VISIBILITY) {
          next[option.key] = DEFAULT_PHARMACY_COLUMN_VISIBILITY[option.key as PharmacyColumnKey];
        } else {
          next[option.key] = false;
        }
      }
      const hasChanges = Object.keys(previous).some((key) => !columnOptionKeys.has(key))
        || Object.keys(next).some((key) => previous[key] !== next[key]);
      if (hasChanges) {
        persistValue(PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY, next);
      }
      return hasChanges ? next : previous;
    });
  }, [columnOptions, columnOptionKeys]);

  const renderCustomValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") {
      return <span className="text-slate-500">—</span>;
    }
    if (typeof value === "boolean") {
      return value ? "Oui" : "Non";
    }
    if (Array.isArray(value)) {
      return value.length ? value.join(", ") : "—";
    }
    return String(value);
  };

  const existingBarcodes = useMemo<ExistingSkuEntry[]>(
    () =>
      items
        .filter((item) => item.barcode && item.barcode.trim().length > 0)
        .map((item) => ({ id: item.id, sku: item.barcode as string })),
    [items]
  );

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setDebouncedSearch(searchValue);
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [searchValue]);

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

  const normalizedSearch = useMemo(() => normalizeSearchTerm(debouncedSearch), [debouncedSearch]);
  const filteredItems = useMemo(() => {
    if (!normalizedSearch) {
      return items;
    }
    return items.filter((item) => {
      const nameMatch = normalizeSearchTerm(item.name).includes(normalizedSearch);
      const barcodeMatch = normalizeSearchTerm(item.barcode ?? "").includes(normalizedSearch);
      return nameMatch || barcodeMatch;
    });
  }, [items, normalizedSearch]);

  useLayoutEffect(() => {
    const tableElement = tableRef.current;
    if (!tableElement) {
      return;
    }

    const measureTable = () => {
      const headerRow = tableElement.querySelector("thead tr");
      const bodyRow = tableElement.querySelector("tbody tr");
      const headerHeight = headerRow?.getBoundingClientRect().height ?? 0;
      const rowHeight = bodyRow?.getBoundingClientRect().height ?? 0;
      const fallbackHeaderHeight = headerHeight || 44;
      const fallbackRowHeight = rowHeight || 44;
      const maxHeight = fallbackHeaderHeight + fallbackRowHeight * 10;
      setTableMaxHeight(maxHeight);
    };

    measureTable();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => {
      measureTable();
    });
    observer.observe(tableElement);

    return () => {
      observer.disconnect();
    };
  }, [filteredItems.length, columnVisibility, canEdit]);

  const lowStockItems = useMemo(
    () =>
      items.filter((item) => {
        const threshold = item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD;
        return threshold > 0 && item.quantity <= threshold;
      }),
    [items]
  );

  const expiredItems = useMemo(
    () => items.filter((item) => getExpirationStatus(item.expiration_date) === "expired"),
    [items]
  );

  const expiringSoonItems = useMemo(
    () => items.filter((item) => getExpirationStatus(item.expiration_date) === "expiring-soon"),
    [items]
  );

  const totalQuantity = useMemo(
    () => items.reduce((total, item) => total + (Number.isFinite(item.quantity) ? item.quantity : 0), 0),
    [items]
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
        supplier_id: selected.supplier_id,
        extra: extraDefaults
      };
    }
    return { ...EMPTY_PHARMACY_PAYLOAD, extra: buildCustomFieldDefaults(activeCustomFields, {}) };
  }, [activeCustomFields, formMode, selected]);

  const [draft, setDraft] = useState<PharmacyFormDraft>(() => createPharmacyFormDraft(formValues));
  const [isBarcodeAuto, setIsBarcodeAuto] = useState<boolean>(
    !(formValues.barcode && formValues.barcode.trim().length > 0)
  );
  const selectedSupplierMissing =
    draft.supplier_id.trim().length > 0 &&
    !suppliers.some((supplier) => String(supplier.id) === draft.supplier_id);

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
      supplier_id: draft.supplier_id.trim() ? Number(draft.supplier_id) : null,
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

  const headerBlock = (
    <section className="min-w-0 space-y-3">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gérez vos médicaments et consommables médicaux.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              setMessage(null);
              setError(null);
              setIsExporting(true);
              try {
                const params = new URLSearchParams();
                if (debouncedSearch) {
                  params.set("q", debouncedSearch);
                }
                const response = await api.get<ArrayBuffer>("/pharmacy/pdf/export", {
                  responseType: "arraybuffer",
                  params: params.toString() ? Object.fromEntries(params.entries()) : undefined
                });
                const blob = new Blob([response.data], { type: "application/pdf" });
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement("a");
                const now = new Date();
                const timestamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
                  now.getDate()
                ).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(
                  2,
                  "0"
                )}`;
                link.href = url;
                link.download = `inventaire_pharmacie_${timestamp}.pdf`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(url);
                setMessage("Inventaire exporté en PDF.");
              } catch (exportError) {
                let errorMessage = "Une erreur est survenue lors de l'export du PDF.";
                if (isAxiosError(exportError)) {
                  const detail = exportError.response?.data?.detail;
                  if (typeof detail === "string" && detail.trim().length > 0) {
                    errorMessage = detail;
                  } else if (exportError.response?.status === 403) {
                    errorMessage = "Accès refusé.";
                  }
                } else if (exportError instanceof Error && exportError.message) {
                  errorMessage = exportError.message;
                }
                setError(errorMessage);
              } finally {
                setIsExporting(false);
              }
            }}
            disabled={isExporting}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
            title="Exporter l'inventaire au format PDF"
          >
            {isExporting ? "Export en cours…" : "Exporter PDF"}
          </button>
          <ColumnManager
            options={columnOptions}
            visibility={columnVisibility}
            onToggle={(key) => toggleColumnVisibility(key, columnOptionKeys)}
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
    </section>
  );

  const searchBlock = (
    <section className="min-w-0 space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <AppTextInput
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
          placeholder="Rechercher par nom ou SKU"
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none sm:flex-1"
          title="Rechercher par nom ou SKU"
        />
        {normalizedSearch ? (
          <p className="text-xs text-slate-400">
            {filteredItems.length} résultat{filteredItems.length > 1 ? "s" : ""}
          </p>
        ) : null}
      </div>
    </section>
  );

  const statsBlock = (
    <section className="min-w-0">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Références</p>
          <p className="mt-2 text-2xl font-semibold text-white">{items.length}</p>
          <p className="text-xs text-slate-400">Articles en base pharmacie.</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Stock total</p>
          <p className="mt-2 text-2xl font-semibold text-white">{totalQuantity}</p>
          <p className="text-xs text-slate-400">Quantité totale enregistrée.</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Alertes stock</p>
          <p className="mt-2 text-2xl font-semibold text-white">{lowStockItems.length}</p>
          <p className="text-xs text-slate-400">Articles sous seuil.</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Péremptions</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {expiredItems.length + expiringSoonItems.length}
          </p>
          <p className="text-xs text-slate-400">Expirés ou bientôt périmés.</p>
        </div>
      </div>
    </section>
  );

  const itemsBlock = (
    <section className="min-h-0 min-w-0 space-y-2">
      <div
        className="min-h-0 w-full min-w-0 overflow-y-auto overflow-x-hidden rounded-lg border border-slate-800"
        style={tableMaxHeight ? { maxHeight: `${tableMaxHeight}px` } : undefined}
      >
        <table ref={tableRef} className="w-full divide-y divide-slate-800">
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
              {columnVisibility.supplier !== false ? (
                <th className="hidden px-4 py-3 text-left lg:table-cell">Fournisseur</th>
              ) : null}
              {columnVisibility.category !== false ? <th className="px-4 py-3 text-left">Catégorie</th> : null}
              {customColumns.map((column) =>
                columnVisibility[column.key] === true ? (
                  <th key={column.key} className="px-4 py-3 text-left">
                    {column.label}
                  </th>
                ) : null
              )}
              {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900">
            {filteredItems.map((item) => {
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
                    <td className="px-4 py-3 font-medium">{highlightMatch(item.name, normalizedSearch)}</td>
                  ) : null}
                  {columnVisibility.barcode !== false ? (
                    <td className="px-4 py-3 text-slate-300">
                      {item.barcode ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="rounded bg-slate-900 px-2 py-1 text-xs text-slate-100">
                            {highlightMatch(item.barcode, normalizedSearch)}
                          </code>
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
                  {columnVisibility.supplier !== false ? (
                    <td className="hidden px-4 py-3 text-slate-300 lg:table-cell">
                      {item.supplier_name ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-slate-200">{item.supplier_name}</span>
                          {item.supplier_email ? null : (
                            <span className="inline-flex items-center rounded border border-slate-600/60 bg-slate-800/70 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                              Email manquant
                            </span>
                          )}
                        </div>
                      ) : item.supplier_id ? (
                        <span className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
                          Fournisseur introuvable
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  ) : null}
                  {columnVisibility.category !== false ? (
                    <td className="px-4 py-3 text-slate-300">
                      {item.category_id ? categoryNames.get(item.category_id) ?? "-" : "-"}
                    </td>
                  ) : null}
                  {customColumns.map((column) =>
                    columnVisibility[column.key] === true ? (
                      <td key={column.key} className="px-4 py-3 text-slate-300">
                        {renderCustomValue(item.extra?.[column.fieldKey])}
                      </td>
                    ) : null
                  )}
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
      {isFetching ? <p className="text-xs text-slate-400">Actualisation...</p> : null}
    </section>
  );

  const sidePanelBlock = (
    <section className="min-w-0 space-y-4">
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">
            {formMode === "edit" ? "Modifier l'article" : "Ajouter un article"}
          </h3>
          {canEdit ? (
            <button
              type="button"
              onClick={() => setIsFormVisible((previous) => !previous)}
              className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:border-slate-600 hover:bg-slate-800"
              title={isFormVisible ? "Masquer le formulaire" : "Afficher le formulaire"}
            >
              {isFormVisible ? "Fermer" : "Ouvrir"}
            </button>
          ) : null}
        </div>
        {canEdit ? (
          isFormVisible ? (
            <form
              key={`${formMode}-${selected?.id ?? "new"}`}
              className="mt-3 space-y-3"
              onSubmit={handleSubmit}
            >
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-name">
                  Nom
                </label>
                <AppTextInput
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
                <AppTextInput
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
                <AppTextInput
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
                <AppTextInput
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
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-supplier">
                  Fournisseur
                </label>
                {canViewSuppliers ? (
                  <select
                    id="pharmacy-supplier"
                    value={draft.supplier_id}
                    onChange={(event) => updateDraft({ supplier_id: event.target.value })}
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                    title="Associez un fournisseur à cet article"
                    disabled={createItem.isPending || updateItem.isPending}
                  >
                    <option value="">Aucun</option>
                    {selectedSupplierMissing ? (
                      <option value={draft.supplier_id}>Fournisseur introuvable</option>
                    ) : null}
                    {suppliers.map((supplier) => (
                      <option key={supplier.id} value={supplier.id}>
                        {supplier.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-400">
                    Fournisseur géré par un admin
                    {draft.supplier_id.trim() ? ` (ID ${draft.supplier_id})` : "."}
                  </div>
                )}
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-quantity">
                  Quantité
                </label>
                <AppTextInput
                  id="pharmacy-quantity"
                  type="number"
                  min={0}
                  value={Number.isNaN(draft.quantity) ? "" : draft.quantity}
                  onChange={(event) => {
                    const { value } = event.target;
                    updateDraft({ quantity: value === "" ? Number.NaN : Number(value) }, false);
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
                <AppTextInput
                  id="pharmacy-low-stock-threshold"
                  type="number"
                  min={0}
                  value={Number.isNaN(draft.low_stock_threshold) ? "" : draft.low_stock_threshold}
                  onChange={(event) => {
                    const { value } = event.target;
                    updateDraft({ low_stock_threshold: value === "" ? Number.NaN : Number(value) }, false);
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
                <AppTextInput
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
                <AppTextInput
                  id="pharmacy-location"
                  value={draft.location}
                  onChange={(event) => updateDraft({ location: event.target.value })}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Emplacement de stockage (armoire, pièce...)"
                />
              </div>
              {activeCustomFields.length > 0 ? (
                <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Champs personnalisés</p>
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
              <div className="flex flex-wrap gap-2">
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
          )
        ) : (
          <p className="mt-3 text-xs text-slate-400">
            Les actions de création et de modification sont réservées aux comptes autorisés.
          </p>
        )}
      </div>

      {canEdit ? (
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
      ) : null}
    </section>
  );

  const categoriesBlock = (
    <section className="min-w-0">
      <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
        <h4 className="text-sm font-semibold text-white">Catégories</h4>
        <p className="text-xs text-slate-400">
          Organisez vos références par familles pour faciliter les recherches et analyses.
        </p>
        {canEdit ? (
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
            isSubmitting={createCategory.isPending || updateCategory.isPending || deleteCategory.isPending}
          />
        ) : (
          <ul className="mt-3 space-y-2 text-xs text-slate-200">
            {categories.length === 0 ? <li className="text-slate-500">Aucune catégorie enregistrée.</li> : null}
            {categories.map((category) => (
              <li key={category.id} className="rounded border border-slate-800 bg-slate-900/70 p-2">
                <p className="text-sm font-semibold text-white">{category.name}</p>
                <p className="text-[11px] text-slate-400">
                  {category.sizes.length > 0 ? category.sizes.join(", ") : "Aucune taille renseignée."}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );

  const lowStockBlock = (
    <section className="min-w-0 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Alertes stock faible</h3>
          <p className="text-xs text-slate-400">Surveillez les références sous leur seuil.</p>
        </div>
        <span className="text-xs font-semibold text-slate-300">{lowStockItems.length}</span>
      </div>
      <div className="min-w-0 overflow-auto rounded-lg border border-slate-800">
        <table className="w-full divide-y divide-slate-800 text-sm text-slate-100">
          <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left">Article</th>
              <th className="px-3 py-2 text-left">Stock</th>
              <th className="px-3 py-2 text-left">Seuil</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900">
            {lowStockItems.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-3 py-3 text-center text-xs text-slate-400">
                  Aucun article sous seuil pour le moment.
                </td>
              </tr>
            ) : (
              lowStockItems.map((item) => (
                <tr key={`low-stock-${item.id}`} className="bg-slate-950">
                  <td className="px-3 py-2 font-medium">{item.name}</td>
                  <td className="px-3 py-2 text-slate-200">{item.quantity}</td>
                  <td className="px-3 py-2 text-slate-300">
                    {item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "pharmacy-header",
      title: "En-tête pharmacie",
      required: true,
      permissions: ["pharmacy"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 4 },
        md: { x: 0, y: 0, w: 10, h: 4 },
        sm: { x: 0, y: 0, w: 6, h: 4 },
        xs: { x: 0, y: 0, w: 4, h: 4 }
      },
      render: () => <EditableBlock id="pharmacy-header">{headerBlock}</EditableBlock>
    },
    {
      id: "pharmacy-search",
      title: "Recherche pharmacie",
      required: true,
      permissions: ["pharmacy"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 4, w: 8, h: 4 },
        md: { x: 0, y: 4, w: 10, h: 4 },
        sm: { x: 0, y: 4, w: 6, h: 4 },
        xs: { x: 0, y: 4, w: 4, h: 4 }
      },
      render: () => <EditableBlock id="pharmacy-search">{searchBlock}</EditableBlock>
    },
    {
      id: "pharmacy-stats",
      title: "Statistiques pharmacie",
      permissions: ["pharmacy"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 8, y: 4, w: 4, h: 8 },
        md: { x: 0, y: 8, w: 10, h: 8 },
        sm: { x: 0, y: 8, w: 6, h: 8 },
        xs: { x: 0, y: 8, w: 4, h: 8 }
      },
      render: () => <EditableBlock id="pharmacy-stats">{statsBlock}</EditableBlock>
    },
    {
      id: "pharmacy-items",
      title: "Articles pharmacie",
      required: true,
      permissions: ["pharmacy"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 8, w: 8, h: 20 },
        md: { x: 0, y: 16, w: 10, h: 20 },
        sm: { x: 0, y: 16, w: 6, h: 20 },
        xs: { x: 0, y: 16, w: 4, h: 20 }
      },
      render: () => <EditableBlock id="pharmacy-items">{itemsBlock}</EditableBlock>
    },
    {
      id: "pharmacy-side-panel",
      title: "Panneau pharmacie",
      permissions: ["pharmacy"],
      minH: 18,
      variant: "plain",
      defaultLayout: {
        lg: { x: 8, y: 12, w: 4, h: 20 },
        md: { x: 0, y: 36, w: 10, h: 20 },
        sm: { x: 0, y: 36, w: 6, h: 20 },
        xs: { x: 0, y: 36, w: 4, h: 20 }
      },
      render: () => <EditableBlock id="pharmacy-side-panel">{sidePanelBlock}</EditableBlock>
    },
    {
      id: "pharmacy-low-stock",
      title: "Alertes stock faible",
      permissions: ["pharmacy"],
      minH: 10,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 28, w: 8, h: 10 },
        md: { x: 0, y: 56, w: 10, h: 10 },
        sm: { x: 0, y: 56, w: 6, h: 10 },
        xs: { x: 0, y: 56, w: 4, h: 10 }
      },
      render: () => <EditableBlock id="pharmacy-low-stock">{lowStockBlock}</EditableBlock>
    },
    {
      id: "pharmacy-categories",
      title: "Catégories pharmacie",
      permissions: ["pharmacy"],
      minH: 12,
      variant: "plain",
      defaultLayout: {
        lg: { x: 8, y: 32, w: 4, h: 12 },
        md: { x: 0, y: 66, w: 10, h: 12 },
        sm: { x: 0, y: 66, w: 6, h: 12 },
        xs: { x: 0, y: 66, w: 4, h: 12 }
      },
      render: () => <EditableBlock id="pharmacy-categories">{categoriesBlock}</EditableBlock>
    },
    {
      id: "pharmacy-lots",
      title: "Lots pharmacie",
      permissions: ["pharmacy"],
      minH: 16,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 44, w: 12, h: 16 },
        md: { x: 0, y: 78, w: 10, h: 16 },
        sm: { x: 0, y: 78, w: 6, h: 16 },
        xs: { x: 0, y: 78, w: 4, h: 16 }
      },
      render: () => (
        <EditableBlock id="pharmacy-lots">
          <PharmacyLotsPanel canEdit={canEdit} />
        </EditableBlock>
      )
    },
    {
      id: "pharmacy-orders",
      title: "Bons de commande",
      permissions: ["pharmacy"],
      minH: 16,
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 60, w: 12, h: 16 },
        md: { x: 0, y: 94, w: 10, h: 16 },
        sm: { x: 0, y: 94, w: 6, h: 16 },
        xs: { x: 0, y: 94, w: 4, h: 16 }
      },
      render: () => (
        <EditableBlock id="pharmacy-orders">
          <PharmacyOrdersPanel canEdit={canEdit} />
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:pharmacy:inventory"
      blocks={blocks}
      className="space-y-6"
    />
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
          <AppTextInput
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
          <AppTextInput
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
        <div className="flex flex-col gap-2 sm:flex-row">
          <AppTextInput
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nouvelle catégorie"
            className="min-w-0 flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Nom de la catégorie"
          />
          <AppTextInput
            value={sizes}
            onChange={(event) => setSizes(event.target.value)}
            placeholder="Tailles ou formats"
            className="min-w-0 flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
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
            <AppTextInput
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

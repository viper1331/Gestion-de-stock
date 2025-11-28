import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import {
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";

import { ColumnManager } from "../../components/ColumnManager";
import { api } from "../../lib/api";
import { resolveMediaUrl } from "../../lib/media";
import { persistValue, readPersistedValue } from "../../lib/persist";
import { ensureUniqueSku, normalizeSkuInput, type ExistingSkuEntry } from "../../lib/sku";
import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";
import {
  DEFAULT_INVENTORY_CONFIG,
  type FrenchGender,
  type InventoryItemNounConfig,
  type InventoryModuleConfig
} from "./config";

interface Category {
  id: number;
  name: string;
  sizes: string[];
}

type VehicleType = "incendie" | "secours_a_personne";

interface Item {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  size: string | null;
  quantity: number;
  low_stock_threshold: number;
  track_low_stock: boolean;
  supplier_id: number | null;
  expiration_date: string | null;
  remise_item_id: number | null;
  remise_quantity?: number | null;
  image_url: string | null;
  lot_id?: number | null;
  lot_name?: string | null;
  lot_names?: string[];
  is_in_lot?: boolean;
  vehicle_type: VehicleType | null;
  assigned_vehicle_names?: string[];
}

interface Movement {
  id: number;
  item_id: number;
  delta: number;
  reason: string | null;
  created_at: string;
}

interface ItemFormValues {
  name: string;
  sku: string;
  category_id: number | null;
  size: string;
  quantity: number;
  low_stock_threshold: number;
  track_low_stock: boolean;
  supplier_id: number | null;
  requires_expiration_date: boolean;
  expiration_date: string;
}

interface ItemFormSubmitPayload {
  values: ItemFormValues;
  imageFile: File | null;
  removeImage: boolean;
}

interface InventoryItemNounForms {
  singular: string;
  plural: string;
  gender: FrenchGender;
  startsWithVowel: boolean;
  singularCapitalized: string;
  definite: string;
  definiteCapitalized: string;
  de: string;
  demonstrative: string;
  demonstrativeCapitalized: string;
  newLabel: string;
  indefinite: string;
  indefiniteCapitalized: string;
}

interface CategoryFormValues {
  name: string;
  sizes: string[];
}

interface Supplier {
  id: number;
  name: string;
}

interface InventoryModuleDashboardProps {
  config?: InventoryModuleConfig;
}

type InventoryColumnKey =
  | "image"
  | "name"
  | "sku"
  | "quantity"
  | "size"
  | "category"
  | "lotMembership"
  | "vehicleType"
  | "supplier"
  | "threshold"
  | "expiration";

const VEHICLE_TYPE_LABELS: Record<VehicleType, string> = {
  incendie: "Incendie",
  secours_a_personne: "Secours à personne"
};

type ExpirationStatus = "expired" | "expiring-soon" | null;

export function InventoryModuleDashboard({ config = DEFAULT_INVENTORY_CONFIG }: InventoryModuleDashboardProps) {
  const queryClient = useQueryClient();
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const supportsItemImages = config.supportsItemImages === true;
  const supportsLowStockOptOut = config.supportsLowStockOptOut === true;
  const supportsExpirationDate = config.supportsExpirationDate === true;
  const itemNoun = useMemo(
    () => createInventoryItemNounForms(config.itemNoun),
    [config.itemNoun]
  );
  const columnStorageKey = `gsp/${config.storageKeyPrefix}/columns`;
  const columnVisibilityStorageKey = `gsp/${config.storageKeyPrefix}/column-visibility`;
  const searchPlaceholder = config.searchPlaceholder ?? "Rechercher par nom ou SKU";
  const barcodePrefix = config.barcodePrefix ?? "SKU";

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setDebouncedSearch(searchValue);
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [searchValue]);

  const openSidebar = () => setIsSidebarOpen(true);
  const closeSidebar = () => {
    setIsSidebarOpen(false);
    setFormMode("create");
    setSelectedItem(null);
  };

  const {
    data: items = [],
    isFetching: isFetchingItems
  } = useQuery({
    queryKey: ["items", { module: config.queryKeyPrefix, search: debouncedSearch }],
    queryFn: async () => {
      const response = await api.get<Item[]>(`${config.basePath}/`, {
        params: debouncedSearch ? { search: debouncedSearch } : undefined
      });
      return response.data;
    }
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories", { module: config.queryKeyPrefix }],
    queryFn: async () => {
      const response = await api.get<Category[]>(`${config.categoriesPath}/`);
      return response.data;
    }
  });

  const suppliersQuery = useQuery({
    queryKey: [
      "suppliers",
      { module: config.supplierModule ?? "all", scope: config.queryKeyPrefix }
    ],
    queryFn: async () => {
      const params = config.supplierModule ? { module: config.supplierModule } : undefined;
      const response = await api.get<Supplier[]>("/suppliers/", { params });
      return response.data;
    }
  });
  const suppliers = suppliersQuery.data ?? [];

  const existingSkus = useMemo<ExistingSkuEntry[]>(
    () =>
      items
        .filter((item) => item.sku && item.sku.trim().length > 0)
        .map((item) => ({ id: item.id, sku: item.sku })),
    [items]
  );

  const createItem = useMutation({
    mutationFn: async (payload: ItemFormValues) => {
      const response = await api.post<Item>(`${config.basePath}/`, payload);
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      setMessage(`${capitalizeFirst(itemNoun.definite)} créé avec succès.`);
    },
    onError: () => setError(`Impossible de créer ${itemNoun.definite}.`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const updateItem = useMutation({
    mutationFn: async ({ itemId, payload }: { itemId: number; payload: ItemFormValues }) => {
      const response = await api.put<Item>(`${config.basePath}/${itemId}`, payload);
      return response.data;
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      await queryClient.invalidateQueries({
        queryKey: ["movements", config.queryKeyPrefix, variables.itemId]
      });
      setMessage(`${capitalizeFirst(itemNoun.definite)} mis à jour.`);
    },
    onError: () => setError(`Impossible de modifier ${itemNoun.definite}.`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const deleteItem = useMutation({
    mutationFn: async (itemId: number) => {
      await api.delete(`${config.basePath}/${itemId}`);
    },
    onSuccess: async () => {
      setMessage(`${capitalizeFirst(itemNoun.definite)} supprimé.`);
      closeSidebar();
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError(`Impossible de supprimer ${itemNoun.definite}.`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const recordMovement = useMutation({
    mutationFn: async ({ itemId, delta, reason }: { itemId: number; delta: number; reason: string }) => {
      await api.post(`${config.basePath}/${itemId}/movements`, { delta, reason: reason || null });
    },
    onSuccess: async (_, variables) => {
      setMessage("Mouvement enregistré.");
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      await queryClient.invalidateQueries({
        queryKey: ["movements", config.queryKeyPrefix, variables.itemId]
      });
    },
    onError: () => setError("Impossible d'enregistrer le mouvement."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const createCategory = useMutation({
    mutationFn: async (payload: CategoryFormValues) => {
      await api.post(`${config.categoriesPath}/`, payload);
    },
    onSuccess: async () => {
      setMessage("Catégorie ajoutée.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: () => setError("Impossible d'ajouter la catégorie.")
  });

  const updateCategoryEntry = useMutation({
    mutationFn: async ({
      categoryId,
      payload
    }: {
      categoryId: number;
      payload: Partial<CategoryFormValues>;
    }) => {
      await api.put(`${config.categoriesPath}/${categoryId}`, payload);
    },
    onSuccess: async () => {
      setMessage("Catégorie mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: () => setError("Impossible de mettre à jour la catégorie.")
  });

  const removeCategory = useMutation({
    mutationFn: async (categoryId: number) => {
      await api.delete(`${config.categoriesPath}/${categoryId}`);
    },
    onSuccess: async () => {
      setMessage("Catégorie supprimée.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError("Suppression de la catégorie impossible."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const exportInventoryPdf = useMutation({
    mutationFn: async () => {
      if (!config.exportPdfPath) {
        throw new Error("Aucun export PDF configuré pour ce module.");
      }
      const response = await api.get<ArrayBuffer>(config.exportPdfPath, {
        responseType: "arraybuffer"
      });
      return response.data;
    },
    onSuccess: (data) => {
      const blob = new Blob([data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const now = new Date();
      const timestamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
        now.getDate()
      ).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
      link.href = url;
      const prefix = config.exportPdfFilenamePrefix || "inventaire";
      link.download = `${prefix}_${timestamp}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      setMessage("Inventaire exporté en PDF.");
    },
    onError: (error) => {
      let message = "Une erreur est survenue lors de l'export du PDF.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      } else if (error instanceof Error && error.message) {
        message = error.message;
      }
      setError(message);
    }
  });

  const baseColumnWidths: Record<InventoryColumnKey, number> = {
    image: 140,
    name: 220,
    sku: 140,
    quantity: 100,
    size: 140,
    category: 150,
    lotMembership: 160,
    vehicleType: 180,
    supplier: 180,
    threshold: 120,
    expiration: 170
  };

  const defaultColumnVisibility: Record<InventoryColumnKey, boolean> = {
    image: supportsItemImages,
    name: true,
    sku: true,
    quantity: true,
    size: true,
    category: true,
    lotMembership: Boolean(config.showLotMembershipColumn),
    vehicleType: Boolean(config.showVehicleTypeColumn),
    supplier: true,
    threshold: true,
    expiration: supportsExpirationDate
  };

  const [columnVisibility, setColumnVisibility] = useState<Record<InventoryColumnKey, boolean>>(() => ({
    ...defaultColumnVisibility,
    ...readPersistedValue<Record<InventoryColumnKey, boolean>>(
      columnVisibilityStorageKey,
      defaultColumnVisibility
    )
  }));

  const toggleColumnVisibility = (key: InventoryColumnKey) => {
    setColumnVisibility((previous) => {
      const isCurrentlyVisible = previous[key] !== false;
      if (isCurrentlyVisible) {
        const visibleCount = Object.values(previous).filter(Boolean).length;
        if (visibleCount <= 1) {
          return previous;
        }
      }
      const next = { ...previous, [key]: !isCurrentlyVisible } as Record<InventoryColumnKey, boolean>;
      persistValue(columnVisibilityStorageKey, next);
      return next;
    });
  };

  const resetColumnVisibility = () => {
    const next = { ...defaultColumnVisibility };
    setColumnVisibility(next);
    persistValue(columnVisibilityStorageKey, next);
  };

  const columnOptions: { key: InventoryColumnKey; label: string }[] = useMemo(() => {
    const options: { key: InventoryColumnKey; label: string }[] = [
      { key: "name", label: itemNoun.singularCapitalized },
      { key: "sku", label: "SKU" },
      { key: "quantity", label: "Quantité" },
      { key: "size", label: "Taille / Variante" },
      { key: "category", label: "Catégorie" },
      ...(config.showLotMembershipColumn
        ? ([{ key: "lotMembership", label: "Lot" }] as const)
        : []),
      ...(config.showVehicleTypeColumn
        ? ([{ key: "vehicleType", label: "Catégorie véhicule" }] as const)
        : []),
      { key: "supplier", label: "Fournisseur" },
      { key: "threshold", label: "Seuil" }
    ];
    if (supportsExpirationDate) {
      options.push({ key: "expiration", label: "Péremption" });
    }
    if (supportsItemImages) {
      return [{ key: "image", label: "Image" }, ...options];
    }
    return options;
  }, [itemNoun.singularCapitalized, supportsExpirationDate, supportsItemImages]);

  const columnWidths = {
    ...baseColumnWidths,
    ...readPersistedValue<Record<string, number>>(columnStorageKey, baseColumnWidths)
  };

  const columnStyles = {
    image: { width: columnWidths.image, minWidth: columnWidths.image },
    name: { width: columnWidths.name, minWidth: columnWidths.name },
    sku: { width: columnWidths.sku, minWidth: columnWidths.sku },
    quantity: { width: columnWidths.quantity, minWidth: columnWidths.quantity },
    size: { width: columnWidths.size, minWidth: columnWidths.size },
    category: { width: columnWidths.category, minWidth: columnWidths.category },
    lotMembership: { width: columnWidths.lotMembership, minWidth: columnWidths.lotMembership },
    vehicleType: { width: columnWidths.vehicleType, minWidth: columnWidths.vehicleType },
    supplier: { width: columnWidths.supplier, minWidth: columnWidths.supplier },
    expiration: { width: columnWidths.expiration, minWidth: columnWidths.expiration },
    threshold: { width: columnWidths.threshold, minWidth: columnWidths.threshold }
  } as const;

  const saveWidth = (key: string, width: number) => {
    persistValue(columnStorageKey, { ...columnWidths, [key]: width });
  };

  const categoryNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const category of categories) {
      map.set(category.id, category.name);
    }
    return map;
  }, [categories]);

  const supplierNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const supplier of suppliers) {
      map.set(supplier.id, supplier.name);
    }
    return map;
  }, [suppliers]);

  useEffect(() => {
    if (selectedItem) {
      const updatedItem = items.find((item) => item.id === selectedItem.id);
      if (!updatedItem) {
        setSelectedItem(null);
        setFormMode("create");
      } else {
        setSelectedItem(updatedItem);
      }
    }
  }, [items, selectedItem]);

  useEffect(() => {
    if (message) {
      const timeout = window.setTimeout(() => setMessage(null), 4000);
      return () => window.clearTimeout(timeout);
    }
    return undefined;
  }, [message]);

  useEffect(() => {
    if (error) {
      const timeout = window.setTimeout(() => setError(null), 5000);
      return () => window.clearTimeout(timeout);
    }
    return undefined;
  }, [error]);

  const formInitialValues: ItemFormValues = useMemo(() => {
    if (formMode === "edit" && selectedItem) {
      return {
        name: selectedItem.name,
        sku: selectedItem.sku,
        category_id: selectedItem.category_id,
        size: selectedItem.size ?? "",
        quantity: selectedItem.quantity,
        low_stock_threshold: selectedItem.low_stock_threshold,
        track_low_stock: selectedItem.track_low_stock,
        supplier_id: selectedItem.supplier_id,
        requires_expiration_date: Boolean(selectedItem.expiration_date),
        expiration_date: selectedItem.expiration_date ?? ""
      };
    }
    return {
      name: "",
      sku: "",
      category_id: null,
      size: "",
      quantity: 0,
      low_stock_threshold: 0,
      track_low_stock: true,
      supplier_id: null,
      requires_expiration_date: false,
      expiration_date: ""
    };
  }, [formMode, selectedItem]);

  const initialImageUrl =
    supportsItemImages && selectedItem ? resolveMediaUrl(selectedItem.image_url) : null;

  const handleSubmitItem = async ({ values, imageFile, removeImage }: ItemFormSubmitPayload) => {
    setMessage(null);
    setError(null);
    try {
      let savedItem: Item | null = null;
      if (formMode === "edit" && selectedItem) {
        savedItem = await updateItem.mutateAsync({ itemId: selectedItem.id, payload: values });
        setSelectedItem(null);
        setFormMode("create");
      } else {
        savedItem = await createItem.mutateAsync(values);
      }

      if (supportsItemImages && savedItem) {
        try {
          if (imageFile) {
            const formData = new FormData();
            formData.append("file", imageFile);
            await api.post(`${config.basePath}/${savedItem.id}/image`, formData, {
              headers: { "Content-Type": "multipart/form-data" }
            });
            setMessage((previous) =>
              previous ? `${previous} Image enregistrée.` : "Image enregistrée."
            );
          } else if (removeImage) {
            await api.delete(`${config.basePath}/${savedItem.id}/image`);
            setMessage((previous) =>
              previous ? `${previous} Image supprimée.` : "Image supprimée."
            );
          }
        } catch (mediaError) {
          console.error(mediaError);
          setMessage(null);
          setError("Impossible de mettre à jour l'image associée.");
        } finally {
          await queryClient.invalidateQueries({ queryKey: ["items"] });
        }
      }
    } catch (submitError) {
      console.error(submitError);
      setError(`Impossible d'enregistrer ${itemNoun.definite}.`);
    }
  };

  const handleDeleteItem = async (itemId: number) => {
    if (window.confirm(`Supprimer définitivement ${itemNoun.demonstrative}?`)) {
      setMessage(null);
      setError(null);
      await deleteItem.mutateAsync(itemId);
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-6 shadow">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{config.title}</h2>
          <p className="text-sm text-slate-400">{config.description}</p>
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <input
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder={searchPlaceholder}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none lg:w-72"
            title={searchPlaceholder}
          />
          <div className="flex flex-wrap items-center gap-2">
            <ColumnManager
              options={columnOptions}
              visibility={columnVisibility}
              onToggle={(key) => toggleColumnVisibility(key as InventoryColumnKey)}
              onReset={resetColumnVisibility}
              description="Choisissez les colonnes à afficher dans la liste."
            />
            {config.exportPdfPath ? (
              <button
                type="button"
                onClick={() => exportInventoryPdf.mutateAsync()}
                disabled={exportInventoryPdf.isPending}
                className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
                title="Exporter l'inventaire au format PDF"
              >
                {exportInventoryPdf.isPending ? "Export en cours…" : "Exporter en PDF"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => {
                if (isSidebarOpen) {
                  closeSidebar();
                } else {
                  openSidebar();
                }
              }}
              className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
              title={
                isSidebarOpen
                  ? "Masquer le panneau latéral des formulaires"
                  : "Afficher le panneau latéral des formulaires"
              }
            >
              {isSidebarOpen ? "Masquer les formulaires" : "Afficher les formulaires"}
            </button>
            <button
              type="button"
              onClick={() => {
                setFormMode("create");
                setSelectedItem(null);
                openSidebar();
              }}
              className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
              title={`${itemNoun.newLabel} dans l'inventaire`}
            >
              {itemNoun.newLabel}
            </button>
          </div>
        </div>
      </header>

      {message ? <Alert tone="success" message={message} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <div className="flex-1 space-y-4">
          <div className="rounded-lg border border-slate-800">
            <div className="max-h-[400px] overflow-y-auto">
              <table className="min-w-full divide-y divide-slate-800">
                <thead className="bg-slate-900/60">
                  <tr>
                    {supportsItemImages && columnVisibility.image !== false ? (
                      <ResizableHeader
                        label="Image"
                        width={columnWidths.image}
                        onResize={(value) => saveWidth("image", value)}
                      />
                    ) : null}
                    {columnVisibility.name !== false ? (
                      <ResizableHeader
                        label={itemNoun.singularCapitalized}
                        width={columnWidths.name}
                        onResize={(value) => saveWidth("name", value)}
                      />
                    ) : null}
                    {columnVisibility.sku !== false ? (
                      <ResizableHeader
                        label="SKU"
                        width={columnWidths.sku}
                        onResize={(value) => saveWidth("sku", value)}
                      />
                    ) : null}
                    {columnVisibility.quantity !== false ? (
                      <ResizableHeader
                        label="Quantité"
                        width={columnWidths.quantity}
                        onResize={(value) => saveWidth("quantity", value)}
                      />
                    ) : null}
                    {columnVisibility.size !== false ? (
                      <ResizableHeader
                        label="Taille / Variante"
                        width={columnWidths.size}
                        onResize={(value) => saveWidth("size", value)}
                      />
                    ) : null}
                    {columnVisibility.category !== false ? (
                      <ResizableHeader
                        label="Catégorie"
                        width={columnWidths.category}
                        onResize={(value) => saveWidth("category", value)}
                      />
                    ) : null}
                    {config.showLotMembershipColumn && columnVisibility.lotMembership !== false ? (
                      <ResizableHeader
                        label="Lot(s)"
                        width={columnWidths.lotMembership}
                        onResize={(value) => saveWidth("lotMembership", value)}
                      />
                    ) : null}
                    {config.showVehicleTypeColumn && columnVisibility.vehicleType !== false ? (
                      <ResizableHeader
                        label="Catégorie véhicule"
                        width={columnWidths.vehicleType}
                        onResize={(value) => saveWidth("vehicleType", value)}
                      />
                    ) : null}
                    {columnVisibility.supplier !== false ? (
                      <ResizableHeader
                        label="Fournisseur"
                        width={columnWidths.supplier}
                        onResize={(value) => saveWidth("supplier", value)}
                      />
                    ) : null}
                    {supportsExpirationDate && columnVisibility.expiration !== false ? (
                      <ResizableHeader
                        label="Péremption"
                        width={columnWidths.expiration}
                        onResize={(value) => saveWidth("expiration", value)}
                      />
                    ) : null}
                    {columnVisibility.threshold !== false ? (
                      <ResizableHeader
                        label="Seuil"
                        width={columnWidths.threshold}
                        onResize={(value) => saveWidth("threshold", value)}
                      />
                    ) : null}
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900 bg-slate-950/60">
                  {items.map((item, index) => {
                    const { isOutOfStock, isLowStock } = getInventoryAlerts(
                      item,
                      supportsLowStockOptOut
                    );
                    const expirationStatus = supportsExpirationDate
                      ? getExpirationStatus(item.expiration_date)
                      : null;
                    const zebraTone = index % 2 === 0 ? "bg-slate-950" : "bg-slate-900/40";
                    const alertTone = isOutOfStock ? "bg-red-950/60" : isLowStock ? "bg-amber-950/40" : "";
                    const selectionTone =
                      selectedItem?.id === item.id && formMode === "edit" ? "ring-1 ring-indigo-500" : "";
                    const imageUrl = resolveMediaUrl(item.image_url);
                    const hasImage = Boolean(imageUrl);
                    const lotNames = item.lot_names?.filter((name) => name.trim().length > 0) ?? [];
                    const isInLot =
                      item.is_in_lot ??
                      (lotNames.length > 0 || Boolean(item.lot_id) || Boolean(item.lot_name));
                    const lotLabel = lotNames.length
                      ? lotNames.join(", ")
                      : item.lot_name ??
                        (isInLot && item.lot_id ? `Lot #${item.lot_id}` : isInLot ? "Oui" : "Aucun");

                    return (
                      <tr key={item.id} className={`${zebraTone} ${alertTone} ${selectionTone}`}>
                        {supportsItemImages && columnVisibility.image !== false ? (
                          <td style={columnStyles.image} className="px-4 py-3 text-sm text-slate-300">
                            {hasImage ? (
                              <img
                                src={imageUrl ?? undefined}
                                alt={`Illustration de ${item.name}`}
                                className="h-12 w-12 rounded border border-slate-700 object-cover"
                              />
                            ) : (
                              <span className="text-xs text-slate-500">Aucune</span>
                            )}
                          </td>
                        ) : null}
                        {columnVisibility.name !== false ? (
                          <td style={columnStyles.name} className="px-4 py-3 text-sm text-slate-100">
                            {item.name}
                          </td>
                        ) : null}
                        {columnVisibility.sku !== false ? (
                          <td style={columnStyles.sku} className="px-4 py-3 text-sm text-slate-300">
                            {item.sku}
                          </td>
                        ) : null}
                        {columnVisibility.quantity !== false ? (
                          <td
                            style={columnStyles.quantity}
                            className={`px-4 py-3 text-sm font-semibold ${
                              isOutOfStock ? "text-red-300" : isLowStock ? "text-amber-200" : "text-slate-100"
                            }`}
                            title={
                              isOutOfStock
                                ? `${itemNoun.demonstrativeCapitalized} est en rupture de stock`
                                : isLowStock
                                  ? "Stock faible"
                                  : undefined
                            }
                          >
                            {item.quantity}
                            {isOutOfStock ? (
                              <span className="ml-2 inline-flex items-center rounded border border-red-500/40 bg-red-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-300">
                                Rupture
                              </span>
                            ) : null}
                            {!isOutOfStock && isLowStock ? (
                              <span className="ml-2 inline-flex items-center rounded border border-amber-400/40 bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
                                Stock faible
                              </span>
                            ) : null}
                          </td>
                        ) : null}
                        {columnVisibility.size !== false ? (
                          <td style={columnStyles.size} className="px-4 py-3 text-sm text-slate-300">
                            {item.size?.trim() || "-"}
                          </td>
                        ) : null}
                        {columnVisibility.category !== false ? (
                          <td style={columnStyles.category} className="px-4 py-3 text-sm text-slate-300">
                            <div className="space-y-1">
                              <div>
                                {item.category_id ? categoryNames.get(item.category_id) ?? "-" : "-"}
                              </div>
                              {item.assigned_vehicle_names?.length ? (
                                <p className="text-xs text-slate-400">
                                  Affecté à : {item.assigned_vehicle_names.join(", ")}
                                </p>
                              ) : null}
                            </div>
                          </td>
                        ) : null}
                        {config.showLotMembershipColumn && columnVisibility.lotMembership !== false ? (
                          <td style={columnStyles.lotMembership} className="px-4 py-3 text-sm text-slate-300">
                            <div className="flex flex-wrap items-center gap-2">
                              <span>{lotLabel}</span>
                              <span
                                className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${isInLot ? "border-emerald-500/40 bg-emerald-500/20 text-emerald-200" : "border-slate-600 bg-slate-800 text-slate-300"}`}
                              >
                                {isInLot ? "Associé" : "Aucun"}
                              </span>
                            </div>
                          </td>
                        ) : null}
                        {config.showVehicleTypeColumn && columnVisibility.vehicleType !== false ? (
                          <td style={columnStyles.vehicleType} className="px-4 py-3 text-sm text-slate-300">
                            {item.vehicle_type ? VEHICLE_TYPE_LABELS[item.vehicle_type] : "Non attribué"}
                          </td>
                        ) : null}
                        {columnVisibility.supplier !== false ? (
                          <td style={columnStyles.supplier} className="px-4 py-3 text-sm text-slate-300">
                            {item.supplier_id ? supplierNames.get(item.supplier_id) ?? "-" : "-"}
                          </td>
                        ) : null}
                        {supportsExpirationDate && columnVisibility.expiration !== false ? (
                          <td
                            style={columnStyles.expiration}
                            className={`px-4 py-3 text-sm ${
                              expirationStatus === "expired"
                                ? "text-red-300"
                                : expirationStatus === "expiring-soon"
                                  ? "text-amber-200"
                                  : "text-slate-300"
                            }`}
                          >
                            {formatExpirationDate(item.expiration_date)}
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
                        {columnVisibility.threshold !== false ? (
                          <td
                            style={columnStyles.threshold}
                            className={`px-4 py-3 text-sm ${isLowStock || isOutOfStock ? "text-slate-200" : "text-slate-300"}`}
                          >
                            {item.low_stock_threshold}
                          </td>
                        ) : null}
                        <td className="px-4 py-3 text-xs text-slate-200">
                          <div className="flex flex-wrap gap-2">
                            <button
                        type="button"
                        onClick={() => {
                              setSelectedItem(item);
                              setFormMode("edit");
                              openSidebar();
                            }}
                            className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                            title={`Modifier les informations de ${item.name}`}
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedItem(item);
                              openSidebar();
                            }}
                            className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                            title={`Saisir un mouvement de stock pour ${item.name}`}
                          >
                            Mouvement
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteItem(item.id)}
                            className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                            title={`Supprimer définitivement ${item.name}`}
                          >
                            Supprimer
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>
          {isFetchingItems ? (
            <p className="text-sm text-slate-400">Actualisation de l'inventaire...</p>
          ) : null}
        </div>

        {isSidebarOpen ? (
          <aside className="w-full space-y-6 lg:w-[380px]">
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-white">
                  {formMode === "edit" ? `Modifier ${itemNoun.definite}` : itemNoun.newLabel}
                </h3>
                <button
                  type="button"
                  onClick={closeSidebar}
                  className="rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 hover:bg-slate-800"
                  title="Fermer le panneau latéral"
                >
                  Fermer
                </button>
              </div>
              <ItemForm
                key={`${formMode}-${selectedItem?.id ?? "new"}`}
                initialValues={formInitialValues}
                categories={categories}
                suppliers={suppliers}
                mode={formMode}
                isSubmitting={createItem.isPending || updateItem.isPending}
                onSubmit={handleSubmitItem}
                onCancel={closeSidebar}
                supportsItemImages={supportsItemImages}
                initialImageUrl={initialImageUrl}
                supportsExpirationDate={supportsExpirationDate}
                itemNoun={itemNoun}
                existingSkus={existingSkus}
                barcodePrefix={barcodePrefix}
                currentItemId={selectedItem?.id ?? null}
                enableLowStockOptOut={supportsLowStockOptOut}
              />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <h3 className="text-sm font-semibold text-white">Mouvement de stock</h3>
              <MovementForm
                item={selectedItem}
                onSubmit={async (values) => {
                  if (!selectedItem) {
                    return;
                  }
                  setMessage(null);
                  setError(null);
                  await recordMovement.mutateAsync({ itemId: selectedItem.id, ...values });
                }}
                isSubmitting={recordMovement.isPending}
                itemNoun={itemNoun}
              />
              <MovementHistory item={selectedItem} config={config} />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <h3 className="text-sm font-semibold text-white">Catégories</h3>
              <CategoryManager
                categories={categories}
                onCreate={async (payload) => {
                  setMessage(null);
                  setError(null);
                  await createCategory.mutateAsync(payload);
                }}
                onDelete={async (categoryId) => {
                  setMessage(null);
                  setError(null);
                  await removeCategory.mutateAsync(categoryId);
                }}
                onUpdate={async (categoryId, payload) => {
                  setMessage(null);
                  setError(null);
                  await updateCategoryEntry.mutateAsync({ categoryId, payload });
                }}
                isSubmitting={
                  createCategory.isPending || removeCategory.isPending || updateCategoryEntry.isPending
                }
              />
            </div>
          </aside>
        ) : null}
      </div>

      {config.showPurchaseOrders ? (
        <PurchaseOrdersPanel
          suppliers={suppliers}
          purchaseOrdersPath={config.purchaseOrdersPath}
          itemsPath={config.purchaseOrdersItemsPath}
          ordersQueryKey={config.purchaseOrdersQueryKey}
          itemsQueryKey={config.purchaseOrdersItemsQueryKey}
          title={config.purchaseOrdersTitle}
          description={config.purchaseOrdersDescription}
          downloadPrefix={config.purchaseOrdersDownloadPrefix}
          itemIdField={config.purchaseOrdersItemIdField}
        />
      ) : null}
    </section>
  );
}

function ResizableHeader({
  label,
  width,
  onResize
}: {
  label: string;
  width: number;
  onResize: (value: number) => void;
}) {
  return (
    <th
      style={{ width, minWidth: width }}
      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400"
    >
      <div className="flex items-center justify-between">
        <span>{label}</span>
        <input
          type="range"
          min={120}
          max={320}
          value={width}
          onChange={(event) => onResize(Number(event.target.value))}
          className="h-1 w-24 cursor-ew-resize appearance-none rounded-full bg-slate-700"
          title={`Ajuster la largeur de la colonne ${label}`}
        />
      </div>
    </th>
  );
}

function Alert({ tone, message }: { tone: "success" | "error"; message: string }) {
  const styles =
    tone === "success"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
      : "border-red-500/40 bg-red-500/10 text-red-200";
  return (
    <div className={`rounded-md border px-4 py-2 text-sm ${styles}`}>
      {message}
    </div>
  );
}

function ItemForm({
  initialValues,
  categories,
  suppliers,
  mode,
  onSubmit,
  onCancel,
  isSubmitting,
  supportsItemImages = false,
  initialImageUrl = null,
  supportsExpirationDate = false,
  itemNoun,
  existingSkus,
  barcodePrefix,
  currentItemId,
  enableLowStockOptOut = false
}: {
  initialValues: ItemFormValues;
  categories: Category[];
  suppliers: Supplier[];
  mode: "create" | "edit";
  onSubmit: (payload: ItemFormSubmitPayload) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
  supportsItemImages?: boolean;
  initialImageUrl?: string | null;
  supportsExpirationDate?: boolean;
  itemNoun: InventoryItemNounForms;
  existingSkus: ExistingSkuEntry[];
  barcodePrefix: string;
  currentItemId: number | null;
  enableLowStockOptOut?: boolean;
}) {
  const [values, setValues] = useState<ItemFormValues>(initialValues);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [removeImage, setRemoveImage] = useState(false);
  const [preview, setPreview] = useState<{ url: string | null; isLocal: boolean }>({
    url: initialImageUrl,
    isLocal: false
  });
  const [isSkuAuto, setIsSkuAuto] = useState<boolean>(
    mode === "create" && initialValues.sku.trim().length === 0
  );
  const selectedCategory = useMemo(
    () => categories.find((category) => category.id === values.category_id),
    [categories, values.category_id]
  );
  const sizeOptionsId =
    selectedCategory && selectedCategory.sizes.length > 0
      ? `category-size-options-${selectedCategory.id}`
      : undefined;

  useEffect(() => {
    setValues(initialValues);
    setIsSkuAuto(mode === "create" && initialValues.sku.trim().length === 0);
  }, [initialValues, mode]);

  useEffect(() => {
    if (!supportsItemImages) {
      return;
    }
    setPreview((previous) => {
      if (previous.isLocal && previous.url) {
        URL.revokeObjectURL(previous.url);
      }
      return { url: initialImageUrl, isLocal: false };
    });
    setImageFile(null);
    setRemoveImage(false);
  }, [initialImageUrl, supportsItemImages]);

  useEffect(() => {
    if (!supportsItemImages) {
      return undefined;
    }
    return () => {
      if (preview.isLocal && preview.url) {
        URL.revokeObjectURL(preview.url);
      }
    };
  }, [preview, supportsItemImages]);

  const handleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!supportsItemImages) {
      return;
    }
    const file = event.target.files?.[0] ?? null;
    setPreview((previous) => {
      if (previous.isLocal && previous.url) {
        URL.revokeObjectURL(previous.url);
      }
      if (!file) {
        return { url: initialImageUrl, isLocal: false };
      }
      const objectUrl = URL.createObjectURL(file);
      return { url: objectUrl, isLocal: true };
    });
    setImageFile(file);
    setRemoveImage(false);
  };

  const handleRemoveImage = () => {
    if (!supportsItemImages) {
      return;
    }
    setPreview((previous) => {
      if (previous.isLocal && previous.url) {
        URL.revokeObjectURL(previous.url);
      }
      return { url: null, isLocal: false };
    });
    setImageFile(null);
    setRemoveImage(Boolean(initialImageUrl));
  };

  const handleRestoreImage = () => {
    if (!supportsItemImages) {
      return;
    }
    setPreview((previous) => {
      if (previous.isLocal && previous.url) {
        URL.revokeObjectURL(previous.url);
      }
      return { url: initialImageUrl, isLocal: false };
    });
    setImageFile(null);
    setRemoveImage(false);
  };

  const handleNameChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextName = event.target.value;
    setValues((prev) => {
      const updated = { ...prev, name: nextName };
      if (isSkuAuto) {
        updated.sku = ensureUniqueSku({
          desiredSku: "",
          prefix: barcodePrefix,
          source: nextName,
          existingSkus,
          excludeId: currentItemId
        });
      }
      return updated;
    });
  };

  const handleSkuChange = (event: ChangeEvent<HTMLInputElement>) => {
    const normalized = normalizeSkuInput(event.target.value);
    setValues((prev) => ({ ...prev, sku: normalized }));
    setIsSkuAuto(normalized.length === 0);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const finalSku = ensureUniqueSku({
      desiredSku: values.sku,
      prefix: barcodePrefix,
      source: values.name.trim(),
      existingSkus,
      excludeId: currentItemId
    });
    const expirationDatePayload =
      supportsExpirationDate && values.requires_expiration_date && values.expiration_date
        ? values.expiration_date
        : null;
    const { requires_expiration_date: _requiresExpirationDate, ...restValues } = values;
    const payload = {
      ...restValues,
      sku: finalSku,
      quantity: Number(values.quantity) || 0,
      low_stock_threshold: Number(values.low_stock_threshold) || 0,
      category_id: values.category_id ?? null,
      supplier_id: values.supplier_id ?? null,
      size: values.size.trim(),
      expiration_date: expirationDatePayload
    };
    await onSubmit({ values: payload, imageFile, removeImage });
    if (mode === "create") {
      setValues({
        name: "",
        sku: "",
        category_id: null,
        size: "",
        quantity: 0,
        low_stock_threshold: 0,
        track_low_stock: true,
        supplier_id: null,
        requires_expiration_date: false,
        expiration_date: ""
      });
      setIsSkuAuto(true);
      if (supportsItemImages) {
        setPreview((previous) => {
          if (previous.isLocal && previous.url) {
            URL.revokeObjectURL(previous.url);
          }
          return { url: null, isLocal: false };
        });
        setImageFile(null);
        setRemoveImage(false);
      }
    }
  };

  return (
    <form className="mt-3 space-y-3" onSubmit={handleSubmit}>
      {supportsItemImages ? (
        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-300" htmlFor="item-image">
            Image {itemNoun.de}
          </label>
          <div className="flex items-start gap-3">
            <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded border border-slate-700 bg-slate-950">
              {preview.url ? (
                <img
                  src={preview.url}
                  alt={values.name ? `Visuel actuel pour ${values.name}` : `Aperçu ${itemNoun.de}`}
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="px-2 text-center text-[11px] text-slate-500">Aucune image</span>
              )}
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <input
                id="item-image"
                type="file"
                accept="image/*"
                onChange={handleImageChange}
                className="w-full text-xs text-slate-200 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-slate-100 hover:file:bg-slate-700"
                title={`Sélectionnez une image illustrant ${itemNoun.de}`}
              />
              <div className="flex flex-wrap gap-2">
                {(preview.url || initialImageUrl) && !removeImage ? (
                  <button
                    type="button"
                    onClick={handleRemoveImage}
                    className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Supprimer l'image
                  </button>
                ) : null}
                {removeImage && initialImageUrl ? (
                  <button
                    type="button"
                    onClick={handleRestoreImage}
                    className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Annuler la suppression
                  </button>
                ) : null}
              </div>
              <p className="text-[11px] text-slate-500">Formats acceptés : JPG, PNG, WEBP ou GIF.</p>
            </div>
          </div>
        </div>
      ) : null}
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-name">
          Nom {itemNoun.de}
        </label>
        <input
          id="item-name"
          value={values.name}
          onChange={handleNameChange}
          required
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title={`Saisissez le nom complet ${itemNoun.de}`}
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-sku">
          SKU / Code-barres
        </label>
        <input
          id="item-sku"
          value={values.sku}
          onChange={handleSkuChange}
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title="Identifiant unique ou code-barres associé"
        />
      </div>
      <div className="flex gap-3">
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="item-quantity">
            Quantité
          </label>
          <input
            id="item-quantity"
            type="number"
            value={values.quantity}
            onChange={(event) => setValues((prev) => ({ ...prev, quantity: Number(event.target.value) }))}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Quantité physique disponible en stock"
          />
        </div>
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="item-threshold">
            Seuil bas
          </label>
          <input
            id="item-threshold"
            type="number"
            value={values.low_stock_threshold}
            onChange={(event) => setValues((prev) => ({ ...prev, low_stock_threshold: Number(event.target.value) }))}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Seuil d'alerte déclenchant les ruptures"
          />
        </div>
      </div>
      {supportsExpirationDate ? (
        <div className="space-y-2 rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
          <label
            className="flex items-start gap-3 text-xs font-semibold text-slate-200"
            htmlFor="item-requires-expiration"
          >
            <input
              id="item-requires-expiration"
              type="checkbox"
              checked={values.requires_expiration_date}
              onChange={(event) =>
                setValues((prev) => ({
                  ...prev,
                  requires_expiration_date: event.target.checked,
                  expiration_date: event.target.checked ? prev.expiration_date : ""
                }))
              }
              className="mt-0.5 h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
            />
            <span className="space-y-1">
              <span>Ce matériel comporte une date de péremption</span>
              <span className="block text-[11px] font-normal text-slate-400">
                Activez cette option si vous devez suivre une date limite d'utilisation.
              </span>
            </span>
          </label>
          {values.requires_expiration_date ? (
            <div className="space-y-1 pl-7">
              <label className="text-xs font-semibold text-slate-300" htmlFor="item-expiration-date">
                Date de péremption
              </label>
              <input
                id="item-expiration-date"
                type="date"
                value={values.expiration_date}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, expiration_date: event.target.value }))
                }
                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              />
            </div>
          ) : null}
        </div>
      ) : null}
      {enableLowStockOptOut ? (
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
          <label className="flex items-start gap-3 text-xs font-semibold text-slate-200" htmlFor="item-track-low-stock">
            <input
              id="item-track-low-stock"
              type="checkbox"
              checked={values.track_low_stock}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, track_low_stock: event.target.checked }))
              }
              className="mt-0.5 h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
            />
            <span className="space-y-1">
              <span>Suivre les alertes de stock</span>
              <span className="block text-[11px] font-normal text-slate-400">
                Désactivez cette option pour exclure ce matériel des alertes de seuil bas dans le tableau
                de bord.
              </span>
            </span>
          </label>
        </div>
      ) : null}
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-size">
          Taille / Variante
        </label>
        <input
          id="item-size"
          value={values.size}
          list={sizeOptionsId}
          onChange={(event) => setValues((prev) => ({ ...prev, size: event.target.value }))}
          placeholder={
            selectedCategory && selectedCategory.sizes.length > 0
              ? "Sélectionnez ou saisissez une taille"
              : undefined
          }
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title="Indiquez la taille ou variante lorsque nécessaire"
        />
        {sizeOptionsId ? (
          <datalist id={sizeOptionsId}>
            {selectedCategory?.sizes.map((size) => (
              <option key={size} value={size} />
            ))}
          </datalist>
        ) : null}
      </div>
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-category">
          Catégorie
        </label>
        <select
          id="item-category"
          value={values.category_id ?? ""}
          onChange={(event) =>
            setValues((prev) => ({
              ...prev,
              category_id: event.target.value ? Number(event.target.value) : null
            }))
          }
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title={`Associez ${itemNoun.definite} à une catégorie métier`}
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
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-supplier">
          Fournisseur
        </label>
        <select
          id="item-supplier"
          value={values.supplier_id ?? ""}
          onChange={(event) =>
            setValues((prev) => ({
              ...prev,
              supplier_id: event.target.value ? Number(event.target.value) : null
            }))
          }
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title={`Associez ${itemNoun.definite} à un fournisseur pour activer les commandes`}
        >
          <option value="">Aucun</option>
          {suppliers.map((supplier) => (
            <option key={supplier.id} value={supplier.id}>
              {supplier.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        {mode === "edit" ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800"
            title="Annuler la modification en cours"
          >
            Annuler
          </button>
        ) : null}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title={
            mode === "edit"
              ? `Enregistrer les modifications ${itemNoun.de}`
              : `Ajouter ${itemNoun.definite} au stock`
          }
        >
          {isSubmitting ? "Enregistrement..." : mode === "edit" ? "Mettre à jour" : "Créer"}
        </button>
      </div>
    </form>
  );
}

function MovementForm({
  item,
  onSubmit,
  isSubmitting,
  itemNoun
}: {
  item: Item | null;
  onSubmit: (values: { delta: number; reason: string }) => Promise<void>;
  isSubmitting: boolean;
  itemNoun: InventoryItemNounForms;
}) {
  const [delta, setDelta] = useState(1);
  const [reason, setReason] = useState("");

  useEffect(() => {
    setDelta(1);
    setReason("");
  }, [item?.id]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!item) {
      return;
    }
    await onSubmit({ delta, reason });
    setDelta(1);
    setReason("");
  };

  return (
    <form className="mt-3 space-y-3" onSubmit={handleSubmit}>
      <p className="text-xs text-slate-400">
        {item
          ? `Ajuster le stock de "${item.name}" (quantité actuelle : ${item.quantity}).`
          : `Sélectionnez ${itemNoun.indefinite} pour appliquer un mouvement.`}
      </p>
      <div className="flex gap-3">
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="movement-delta">
            Variation
          </label>
          <input
            id="movement-delta"
            type="number"
            value={delta}
            onChange={(event) => setDelta(Number(event.target.value))}
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Indiquez la variation positive ou négative à appliquer"
          />
        </div>
        <div className="flex-1 space-y-1">
          <label className="text-xs font-semibold text-slate-300" htmlFor="movement-reason">
            Motif
          </label>
          <input
            id="movement-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Inventaire, sortie..."
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Précisez la raison du mouvement pour le suivi"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={!item || isSubmitting}
        className="w-full rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
        title={item ? "Valider ce mouvement de stock" : `Sélectionnez d'abord ${itemNoun.indefinite}`}
      >
        {isSubmitting ? "Enregistrement..." : "Valider le mouvement"}
      </button>
    </form>
  );
}

function MovementHistory({
  item,
  config
}: {
  item: Item | null;
  config: InventoryModuleConfig;
}) {
  const { data: movements = [], isFetching } = useQuery({
    queryKey: ["movements", config.queryKeyPrefix, item?.id ?? "none"],
    queryFn: async () => {
      if (!item) {
        return [] as Movement[];
      }
      const response = await api.get<Movement[]>(`${config.basePath}/${item.id}/movements`);
      return response.data;
    },
    enabled: Boolean(item),
    placeholderData: [] as Movement[]
  });

  if (!item) {
    return <p className="mt-3 text-xs text-slate-400">Aucun historique à afficher.</p>;
  }

  return (
    <div className="mt-4 space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Derniers mouvements</h4>
      {isFetching ? <p className="text-xs text-slate-400">Chargement...</p> : null}
      <ul className="space-y-2 text-xs text-slate-200">
        {movements.length === 0 ? (
          <li className="text-slate-500">Aucun mouvement enregistré.</li>
        ) : null}
        {movements.slice(0, 6).map((movement) => (
          <li key={movement.id} className="rounded border border-slate-800 bg-slate-950 p-2">
            <div className="flex items-center justify-between">
              <span
                className={`font-semibold ${
                  movement.delta >= 0 ? "text-emerald-300" : "text-red-300"
                }`}
              >
                {movement.delta >= 0 ? `+${movement.delta}` : movement.delta}
              </span>
              <span className="text-[10px] text-slate-400">{formatDate(movement.created_at)}</span>
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

function CategoryManager({
  categories,
  onCreate,
  onDelete,
  onUpdate,
  isSubmitting
}: {
  categories: Category[];
  onCreate: (values: CategoryFormValues) => Promise<void>;
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

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      return;
    }
    const parsedSizes = parseSizesInput(sizes);
    await onCreate({ name: trimmedName, sizes: parsedSizes });
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
    <div className="space-y-3">
      <form className="space-y-2" onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nouvelle catégorie"
            className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            title="Nom de la nouvelle catégorie à créer"
          />
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
            title="Ajouter cette catégorie"
          >
            Ajouter
          </button>
        </div>
        <input
          value={sizes}
          onChange={(event) => setSizes(event.target.value)}
          placeholder="Tailles (séparées par des virgules)"
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
          title="Définissez les tailles proposées pour cette catégorie"
        />
      </form>
      <ul className="space-y-2 text-xs text-slate-200">
        {categories.length === 0 ? (
          <li className="text-slate-500">Aucune catégorie définie.</li>
        ) : null}
        {categories.map((category) => {
          const currentValue = editedSizes[category.id] ?? category.sizes.join(", ");
          return (
            <li key={category.id} className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex-1 space-y-2">
                  <p className="text-sm font-semibold text-slate-100">{category.name}</p>
                  <input
                    value={currentValue}
                    onChange={(event) =>
                      setEditedSizes((previous) => ({ ...previous, [category.id]: event.target.value }))
                    }
                    placeholder="Tailles (séparées par des virgules)"
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                    title="Modifiez les tailles disponibles pour cette catégorie"
                  />
                </div>
                <div className="flex gap-2 sm:flex-col">
                  <button
                    type="button"
                    onClick={() => handleSave(category.id)}
                    disabled={isSubmitting}
                    className="rounded bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    title="Enregistrer les tailles saisies"
                  >
                    Enregistrer
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await onDelete(category.id);
                    }}
                    disabled={isSubmitting}
                    className="rounded bg-slate-800 px-3 py-2 text-[10px] font-semibold hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
                    title="Supprimer cette catégorie"
                  >
                    Supprimer
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function createInventoryItemNounForms(
  config?: InventoryItemNounConfig
): InventoryItemNounForms {
  const singular = (config?.singular ?? "article").trim() || "article";
  const plural = (config?.plural ?? `${singular}s`).trim() || `${singular}s`;
  const gender: FrenchGender = config?.gender ?? "masculine";
  const firstChar = singular.charAt(0).toLowerCase();
  const startsWithVowel = Boolean(firstChar) && "aeiouyh".includes(firstChar);

  const definite = startsWithVowel
    ? `l'${singular}`
    : gender === "feminine"
      ? `la ${singular}`
      : `le ${singular}`;
  const definiteCapitalized = capitalizeFirst(definite);

  const de = startsWithVowel
    ? `de l'${singular}`
    : gender === "feminine"
      ? `de la ${singular}`
      : `du ${singular}`;

  const indefinite = gender === "feminine" ? `une ${singular}` : `un ${singular}`;
  const indefiniteCapitalized = capitalizeFirst(indefinite);

  const demonstrativeBase = gender === "feminine" ? "cette" : startsWithVowel ? "cet" : "ce";
  const demonstrative = `${demonstrativeBase} ${singular}`;
  const demonstrativeCapitalized = capitalizeFirst(demonstrative);

  const newLabel =
    gender === "feminine"
      ? `Nouvelle ${singular}`
      : startsWithVowel
        ? `Nouvel ${singular}`
        : `Nouveau ${singular}`;

  return {
    singular,
    plural,
    gender,
    startsWithVowel,
    singularCapitalized: capitalizeFirst(singular),
    definite,
    definiteCapitalized,
    de,
    demonstrative,
    demonstrativeCapitalized,
    newLabel,
    indefinite,
    indefiniteCapitalized
  };
}

function capitalizeFirst(text: string): string {
  if (!text) {
    return text;
  }
  if (text.startsWith("l'")) {
    return `L'${text.slice(2)}`;
  }
  if (text.startsWith("d'")) {
    return `D'${text.slice(2)}`;
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function getInventoryAlerts(item: Item, allowOptOut = false) {
  const trackingEnabled = allowOptOut ? item.track_low_stock : true;
  const isOutOfStock = trackingEnabled && item.quantity <= 0;
  const hasThreshold = item.low_stock_threshold > 0;
  const isLowStock =
    trackingEnabled && !isOutOfStock && hasThreshold && item.quantity <= item.low_stock_threshold;

  return { isOutOfStock, isLowStock, trackingEnabled };
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

  const diffInDays = Math.floor((expiration.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

  if (diffInDays < 0) {
    return "expired";
  }

  if (diffInDays <= 30) {
    return "expiring-soon";
  }

  return null;
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

function formatExpirationDate(value: string | null) {
  if (!value) {
    return "-";
  }

  try {
    return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

function formatDate(value: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: "short"
    }).format(new Date(value));
  } catch (error) {
    return value;
  }
}

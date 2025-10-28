import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";

import { ColumnManager } from "../../components/ColumnManager";
import { api } from "../../lib/api";
import { persistValue, readPersistedValue } from "../../lib/persist";
import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";

interface Category {
  id: number;
  name: string;
  sizes: string[];
}

interface Item {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  size: string | null;
  quantity: number;
  low_stock_threshold: number;
  supplier_id: number | null;
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
  supplier_id: number | null;
}

interface CategoryFormValues {
  name: string;
  sizes: string[];
}

interface Supplier {
  id: number;
  name: string;
}

const COLUMN_STORAGE_KEY = "gsp/columns";
const COLUMN_VISIBILITY_STORAGE_KEY = "gsp/inventory-column-visibility";

type InventoryColumnKey =
  | "name"
  | "sku"
  | "quantity"
  | "size"
  | "category"
  | "supplier"
  | "threshold";

export function Dashboard() {
  const queryClient = useQueryClient();
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    queryKey: ["items", { search: debouncedSearch }],
    queryFn: async () => {
      const response = await api.get<Item[]>("/items/", {
        params: debouncedSearch ? { search: debouncedSearch } : undefined
      });
      return response.data;
    }
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: async () => {
      const response = await api.get<Category[]>("/categories/");
      return response.data;
    }
  });

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers", { module: "suppliers" }],
    queryFn: async () => {
      const response = await api.get<Supplier[]>("/suppliers/", {
        params: { module: "suppliers" }
      });
      return response.data;
    }
  });

  const createItem = useMutation({
    mutationFn: async (payload: ItemFormValues) => {
      await api.post("/items/", payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      setMessage("Article créé avec succès.");
    },
    onError: () => setError("Impossible de créer l'article."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const updateItem = useMutation({
    mutationFn: async ({ itemId, payload }: { itemId: number; payload: ItemFormValues }) => {
      await api.put(`/items/${itemId}`, payload);
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      await queryClient.invalidateQueries({ queryKey: ["movements", variables.itemId] });
      setMessage("Article mis à jour.");
    },
    onError: () => setError("La mise à jour a échoué."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const deleteItem = useMutation({
    mutationFn: async (itemId: number) => {
      await api.delete(`/items/${itemId}`);
    },
    onSuccess: async () => {
      setMessage("Article supprimé.");
      closeSidebar();
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError("Suppression impossible."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const recordMovement = useMutation({
    mutationFn: async ({ itemId, delta, reason }: { itemId: number; delta: number; reason: string }) => {
      await api.post(`/items/${itemId}/movements`, { delta, reason: reason || null });
    },
    onSuccess: async (_, variables) => {
      setMessage("Mouvement enregistré.");
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      await queryClient.invalidateQueries({ queryKey: ["movements", variables.itemId] });
    },
    onError: () => setError("Impossible d'enregistrer le mouvement."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const createCategory = useMutation({
    mutationFn: async (payload: CategoryFormValues) => {
      await api.post("/categories/", payload);
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
      await api.put(`/categories/${categoryId}`, payload);
    },
    onSuccess: async () => {
      setMessage("Catégorie mise à jour.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: () => setError("Impossible de mettre à jour la catégorie.")
  });

  const removeCategory = useMutation({
    mutationFn: async (categoryId: number) => {
      await api.delete(`/categories/${categoryId}`);
    },
    onSuccess: async () => {
      setMessage("Catégorie supprimée.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: () => setError("Suppression de la catégorie impossible."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["reports"] })
  });

  const defaultColumnWidths: Record<string, number> = {
    name: 220,
    sku: 140,
    quantity: 100,
    size: 140,
    category: 150,
    supplier: 180,
    threshold: 120
  };

  const defaultColumnVisibility: Record<InventoryColumnKey, boolean> = {
    name: true,
    sku: true,
    quantity: true,
    size: true,
    category: true,
    supplier: true,
    threshold: true
  };

  const [columnVisibility, setColumnVisibility] = useState<Record<InventoryColumnKey, boolean>>(() => ({
    ...readPersistedValue<Record<InventoryColumnKey, boolean>>(
      COLUMN_VISIBILITY_STORAGE_KEY,
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
      persistValue(COLUMN_VISIBILITY_STORAGE_KEY, next);
      return next;
    });
  };

  const resetColumnVisibility = () => {
    const next = { ...defaultColumnVisibility };
    setColumnVisibility(next);
    persistValue(COLUMN_VISIBILITY_STORAGE_KEY, next);
  };

  const columnOptions: { key: InventoryColumnKey; label: string }[] = [
    { key: "name", label: "Article" },
    { key: "sku", label: "SKU" },
    { key: "quantity", label: "Quantité" },
    { key: "size", label: "Taille / Variante" },
    { key: "category", label: "Catégorie" },
    { key: "supplier", label: "Fournisseur" },
    { key: "threshold", label: "Seuil" }
  ];

  const columnWidths = {
    ...defaultColumnWidths,
    ...readPersistedValue<Record<string, number>>(COLUMN_STORAGE_KEY, defaultColumnWidths)
  };

  const saveWidth = (key: string, width: number) => {
    persistValue(COLUMN_STORAGE_KEY, { ...columnWidths, [key]: width });
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
        supplier_id: selectedItem.supplier_id
      };
    }
    return {
      name: "",
      sku: "",
      category_id: null,
      size: "",
      quantity: 0,
      low_stock_threshold: 0,
      supplier_id: null
    };
  }, [formMode, selectedItem]);

  const handleSubmitItem = async (values: ItemFormValues) => {
    setMessage(null);
    setError(null);
    if (formMode === "edit" && selectedItem) {
      await updateItem.mutateAsync({ itemId: selectedItem.id, payload: values });
      setSelectedItem(null);
      setFormMode("create");
    } else {
      await createItem.mutateAsync(values);
    }
  };

  const handleDeleteItem = async (itemId: number) => {
    if (window.confirm("Supprimer définitivement cet article ?")) {
      setMessage(null);
      setError(null);
      await deleteItem.mutateAsync(itemId);
    }
  };

  return (
    <section className="space-y-6">
      <header className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-6 shadow">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Inventaire</h2>
          <p className="text-sm text-slate-400">
            Retrouvez l'ensemble des articles, appliquez des mouvements et gérez les catégories.
          </p>
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <input
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Rechercher par nom ou SKU"
            className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none lg:w-72"
            title="Filtrer la liste des articles par nom ou SKU"
          />
          <div className="flex flex-wrap items-center gap-2">
            <ColumnManager
              options={columnOptions}
              visibility={columnVisibility}
              onToggle={(key) => toggleColumnVisibility(key as InventoryColumnKey)}
              onReset={resetColumnVisibility}
              description="Choisissez les colonnes à afficher dans la liste."
            />
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
              title="Créer un nouvel article dans l'inventaire"
            >
              Nouvel article
            </button>
          </div>
        </div>
      </header>

      {message ? <Alert tone="success" message={message} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <div className="flex-1 space-y-4">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60">
                <tr>
                  {columnVisibility.name !== false ? (
                    <ResizableHeader
                      label="Article"
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
                  {columnVisibility.supplier !== false ? (
                    <ResizableHeader
                      label="Fournisseur"
                      width={columnWidths.supplier}
                      onResize={(value) => saveWidth("supplier", value)}
                    />
                  ) : null}
                  {columnVisibility.threshold !== false ? (
                    <ResizableHeader
                      label="Seuil"
                      width={columnWidths.threshold}
                      onResize={(value) => saveWidth("threshold", value)}
                    />
                  ) : null}
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900 bg-slate-950/60">
                {items.map((item, index) => {
                  const { isOutOfStock, isLowStock } = getInventoryAlerts(item);
                  const zebraTone = index % 2 === 0 ? "bg-slate-950" : "bg-slate-900/40";
                  const alertTone = isOutOfStock ? "bg-red-950/60" : isLowStock ? "bg-amber-950/40" : "";
                  const selectionTone =
                    selectedItem?.id === item.id && formMode === "edit" ? "ring-1 ring-indigo-500" : "";

                  return (
                    <tr key={item.id} className={`${zebraTone} ${alertTone} ${selectionTone}`}>
                      {columnVisibility.name !== false ? (
                        <td className="px-4 py-3 text-sm text-slate-100">{item.name}</td>
                      ) : null}
                      {columnVisibility.sku !== false ? (
                        <td className="px-4 py-3 text-sm text-slate-300">{item.sku}</td>
                      ) : null}
                      {columnVisibility.quantity !== false ? (
                        <td
                          className={`px-4 py-3 text-sm font-semibold ${
                            isOutOfStock ? "text-red-300" : isLowStock ? "text-amber-200" : "text-slate-100"
                          }`}
                          title={
                            isOutOfStock
                              ? "Cet article est en rupture de stock"
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
                        <td className="px-4 py-3 text-sm text-slate-300">{item.size?.trim() || "-"}</td>
                      ) : null}
                      {columnVisibility.category !== false ? (
                        <td className="px-4 py-3 text-sm text-slate-300">
                          {item.category_id ? categoryNames.get(item.category_id) ?? "-" : "-"}
                        </td>
                      ) : null}
                      {columnVisibility.supplier !== false ? (
                        <td className="px-4 py-3 text-sm text-slate-300">
                          {item.supplier_id ? supplierNames.get(item.supplier_id) ?? "-" : "-"}
                        </td>
                      ) : null}
                      {columnVisibility.threshold !== false ? (
                        <td className={`px-4 py-3 text-sm ${isLowStock || isOutOfStock ? "text-slate-200" : "text-slate-300"}`}>
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
          {isFetchingItems ? (
            <p className="text-sm text-slate-400">Actualisation de l'inventaire...</p>
          ) : null}
        </div>

        {isSidebarOpen ? (
          <aside className="w-full space-y-6 lg:w-[380px]">
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-white">
                  {formMode === "edit" ? "Modifier l'article" : "Nouvel article"}
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
              />
              <MovementHistory item={selectedItem} />
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

      <PurchaseOrdersPanel suppliers={suppliers} />
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
    <th style={{ width }} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
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
  isSubmitting
}: {
  initialValues: ItemFormValues;
  categories: Category[];
  suppliers: Supplier[];
  mode: "create" | "edit";
  onSubmit: (values: ItemFormValues) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
}) {
  const [values, setValues] = useState<ItemFormValues>(initialValues);
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
  }, [initialValues]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const payload = {
      ...values,
      quantity: Number(values.quantity) || 0,
      low_stock_threshold: Number(values.low_stock_threshold) || 0,
      category_id: values.category_id ?? null,
      supplier_id: values.supplier_id ?? null,
      size: values.size.trim()
    };
    await onSubmit(payload);
    if (mode === "create") {
      setValues({
        name: "",
        sku: "",
        category_id: null,
        size: "",
        quantity: 0,
        low_stock_threshold: 0,
        supplier_id: null
      });
    }
  };

  return (
    <form className="mt-3 space-y-3" onSubmit={handleSubmit}>
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-name">
          Nom de l'article
        </label>
        <input
          id="item-name"
          value={values.name}
          onChange={(event) => setValues((prev) => ({ ...prev, name: event.target.value }))}
          required
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          title="Saisissez le nom complet de l'article"
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs font-semibold text-slate-300" htmlFor="item-sku">
          SKU / Code-barres
        </label>
        <input
          id="item-sku"
          value={values.sku}
          onChange={(event) => setValues((prev) => ({ ...prev, sku: event.target.value }))}
          required
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
          title="Associez l'article à une catégorie métier"
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
          title="Associez l'article à un fournisseur pour activer les commandes"
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
          title={mode === "edit" ? "Enregistrer les modifications de l'article" : "Ajouter l'article au stock"}
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
  isSubmitting
}: {
  item: Item | null;
  onSubmit: (values: { delta: number; reason: string }) => Promise<void>;
  isSubmitting: boolean;
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
          : "Sélectionnez un article pour appliquer un mouvement."}
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
        title={item ? "Valider ce mouvement de stock" : "Sélectionnez d'abord un article"}
      >
        {isSubmitting ? "Enregistrement..." : "Valider le mouvement"}
      </button>
    </form>
  );
}

function MovementHistory({ item }: { item: Item | null }) {
  const { data: movements = [], isFetching } = useQuery({
    queryKey: ["movements", item?.id ?? "none"],
    queryFn: async () => {
      if (!item) {
        return [] as Movement[];
      }
      const response = await api.get<Movement[]>(`/items/${item.id}/movements`);
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

function getInventoryAlerts(item: Item) {
  const isOutOfStock = item.quantity <= 0;
  const hasThreshold = item.low_stock_threshold > 0;
  const isLowStock = !isOutOfStock && hasThreshold && item.quantity <= item.low_stock_threshold;

  return { isOutOfStock, isLowStock };
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

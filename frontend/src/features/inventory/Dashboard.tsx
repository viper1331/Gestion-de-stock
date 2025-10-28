import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";

import { api } from "../../lib/api";
import { persistValue, readPersistedValue } from "../../lib/persist";

interface Category {
  id: number;
  name: string;
}

interface Item {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  size: string | null;
  quantity: number;
  low_stock_threshold: number;
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
}

const COLUMN_STORAGE_KEY = "gsp/columns";

export function Dashboard() {
  const queryClient = useQueryClient();
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setDebouncedSearch(searchValue);
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [searchValue]);

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
      setSelectedItem(null);
      setFormMode("create");
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
    mutationFn: async (name: string) => {
      await api.post("/categories/", { name });
    },
    onSuccess: async () => {
      setMessage("Catégorie ajoutée.");
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: () => setError("Impossible d'ajouter la catégorie.")
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

  const columnWidths = readPersistedValue<Record<string, number>>(COLUMN_STORAGE_KEY, {
    name: 220,
    sku: 140,
    quantity: 100,
    category: 150,
    threshold: 120
  });

  const saveWidth = (key: string, width: number) => {
    persistValue(COLUMN_STORAGE_KEY, { ...columnWidths, [key]: width });
  };

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
        low_stock_threshold: selectedItem.low_stock_threshold
      };
    }
    return {
      name: "",
      sku: "",
      category_id: null,
      size: "",
      quantity: 0,
      low_stock_threshold: 0
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
      <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Inventaire</h2>
          <p className="text-sm text-slate-400">
            Retrouvez l'ensemble des articles, appliquez des mouvements et gérez les catégories.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <input
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Rechercher par nom ou SKU"
            className="w-64 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => {
              setFormMode("create");
              setSelectedItem(null);
            }}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
          >
            Nouvel article
          </button>
        </div>
      </header>

      {message ? <Alert tone="success" message={message} /> : null}
      {error ? <Alert tone="error" message={error} /> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60">
                <tr>
                  <ResizableHeader label="Article" width={columnWidths.name} onResize={(value) => saveWidth("name", value)} />
                  <ResizableHeader label="SKU" width={columnWidths.sku} onResize={(value) => saveWidth("sku", value)} />
                  <ResizableHeader
                    label="Quantité"
                    width={columnWidths.quantity}
                    onResize={(value) => saveWidth("quantity", value)}
                  />
                  <ResizableHeader
                    label="Catégorie"
                    width={columnWidths.category}
                    onResize={(value) => saveWidth("category", value)}
                  />
                  <ResizableHeader
                    label="Seuil"
                    width={columnWidths.threshold}
                    onResize={(value) => saveWidth("threshold", value)}
                  />
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900 bg-slate-950/60">
                {items.map((item, index) => (
                  <tr
                    key={item.id}
                    className={`${
                      index % 2 === 0 ? "bg-slate-950" : "bg-slate-900/40"
                    } ${selectedItem?.id === item.id && formMode === "edit" ? "ring-1 ring-indigo-500" : ""}`}
                  >
                    <td className="px-4 py-3 text-sm text-slate-100">{item.name}</td>
                    <td className="px-4 py-3 text-sm text-slate-300">{item.sku}</td>
                    <td className="px-4 py-3 text-sm font-semibold text-slate-100">{item.quantity}</td>
                    <td className="px-4 py-3 text-sm text-slate-300">
                      {categories.find((category) => category.id === item.category_id)?.name ?? "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-300">{item.low_stock_threshold}</td>
                    <td className="px-4 py-3 text-xs text-slate-200">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedItem(item);
                            setFormMode("edit");
                          }}
                          className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                        >
                          Modifier
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedItem(item);
                          }}
                          className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                        >
                          Mouvement
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteItem(item.id)}
                          className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                        >
                          Supprimer
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {isFetchingItems ? (
            <p className="text-sm text-slate-400">Actualisation de l'inventaire...</p>
          ) : null}
        </div>

        <aside className="space-y-6">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-white">
              {formMode === "edit" ? "Modifier l'article" : "Nouvel article"}
            </h3>
            <ItemForm
              key={`${formMode}-${selectedItem?.id ?? "new"}`}
              initialValues={formInitialValues}
              categories={categories}
              mode={formMode}
              isSubmitting={createItem.isPending || updateItem.isPending}
              onSubmit={handleSubmitItem}
              onCancel={() => {
                setFormMode("create");
                setSelectedItem(null);
              }}
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
              onCreate={async (name) => {
                setMessage(null);
                setError(null);
                await createCategory.mutateAsync(name);
              }}
              onDelete={async (categoryId) => {
                setMessage(null);
                setError(null);
                await removeCategory.mutateAsync(categoryId);
              }}
              isSubmitting={createCategory.isPending || removeCategory.isPending}
            />
          </div>
        </aside>
      </div>
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
  mode,
  onSubmit,
  onCancel,
  isSubmitting
}: {
  initialValues: ItemFormValues;
  categories: Category[];
  mode: "create" | "edit";
  onSubmit: (values: ItemFormValues) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
}) {
  const [values, setValues] = useState<ItemFormValues>(initialValues);

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
      size: values.size.trim()
    };
    await onSubmit(payload);
    if (mode === "create") {
      setValues({ name: "", sku: "", category_id: null, size: "", quantity: 0, low_stock_threshold: 0 });
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
          onChange={(event) => setValues((prev) => ({ ...prev, size: event.target.value }))}
          className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
        />
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
        >
          <option value="">Aucune</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
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
          >
            Annuler
          </button>
        ) : null}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
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
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={!item || isSubmitting}
        className="w-full rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
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
  isSubmitting
}: {
  categories: Category[];
  onCreate: (name: string) => Promise<void>;
  onDelete: (categoryId: number) => Promise<void>;
  isSubmitting: boolean;
}) {
  const [name, setName] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    await onCreate(name.trim());
    setName("");
  };

  return (
    <div className="space-y-3">
      <form className="flex gap-2" onSubmit={handleSubmit}>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Nouvelle catégorie"
          className="flex-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
        >
          Ajouter
        </button>
      </form>
      <ul className="space-y-1 text-xs text-slate-200">
        {categories.length === 0 ? (
          <li className="text-slate-500">Aucune catégorie définie.</li>
        ) : null}
        {categories.map((category) => (
          <li key={category.id} className="flex items-center justify-between rounded border border-slate-800 bg-slate-950 px-3 py-2">
            <span>{category.name}</span>
            <button
              type="button"
              onClick={() => onDelete(category.id)}
              className="rounded bg-slate-800 px-2 py-1 text-[10px] font-semibold hover:bg-slate-700"
            >
              Supprimer
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
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

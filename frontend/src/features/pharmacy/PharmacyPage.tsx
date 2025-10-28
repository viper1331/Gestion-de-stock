import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ColumnManager } from "../../components/ColumnManager";
import { api } from "../../lib/api";
import { persistValue, readPersistedValue } from "../../lib/persist";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { PharmacyOrdersPanel } from "./PharmacyOrdersPanel";

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
}

type PharmacyColumnKey =
  | "name"
  | "barcode"
  | "dosage"
  | "packaging"
  | "quantity"
  | "low_stock_threshold"
  | "expiration"
  | "location";

const PHARMACY_COLUMN_VISIBILITY_STORAGE_KEY = "gsp/pharmacy-column-visibility";

const DEFAULT_PHARMACY_COLUMN_VISIBILITY: Record<PharmacyColumnKey, boolean> = {
  name: true,
  barcode: true,
  dosage: true,
  packaging: true,
  quantity: true,
  low_stock_threshold: true,
  expiration: true,
  location: true
};

const PHARMACY_COLUMN_OPTIONS: { key: PharmacyColumnKey; label: string }[] = [
  { key: "name", label: "Nom" },
  { key: "barcode", label: "Code-barres" },
  { key: "dosage", label: "Dosage" },
  { key: "packaging", label: "Conditionnement" },
  { key: "quantity", label: "Quantité" },
  { key: "low_stock_threshold", label: "Seuil faible" },
  { key: "expiration", label: "Expiration" },
  { key: "location", label: "Localisation" }
];

export function PharmacyPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PharmacyItem | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const { data: items = [], isFetching } = useQuery({
    queryKey: ["pharmacy"],
    queryFn: async () => {
      const response = await api.get<PharmacyItem[]>("/pharmacy/");
      return response.data;
    },
    enabled: canView
  });

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

  const apiBaseUrl = (api.defaults.baseURL ?? "").replace(/\/$/, "");

  const formValues = useMemo<PharmacyPayload>(() => {
    if (formMode === "edit" && selected) {
      return {
        name: selected.name,
        dosage: selected.dosage,
        packaging: selected.packaging,
        barcode: selected.barcode,
        quantity: selected.quantity,
        low_stock_threshold: selected.low_stock_threshold,
        expiration_date: selected.expiration_date,
        location: selected.location
      };
    }
    return {
      name: "",
      dosage: "",
      packaging: "",
      barcode: "",
      quantity: 0,
      low_stock_threshold: DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD,
      expiration_date: "",
      location: ""
    };
  }, [formMode, selected]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
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
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
          <p className="text-sm text-slate-400">Suivi des stocks pharmaceutiques.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const rawThreshold = formData.get("low_stock_threshold");
    const normalizedThreshold =
      rawThreshold === null || (typeof rawThreshold === "string" && rawThreshold.trim() === "")
        ? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD
        : Number(rawThreshold);
    const payload: PharmacyPayload = {
      name: (formData.get("name") as string).trim(),
      dosage: ((formData.get("dosage") as string) || "").trim() || null,
      packaging: ((formData.get("packaging") as string) || "").trim() || null,
      barcode: ((formData.get("barcode") as string) || "").trim() || null,
      quantity: Number(formData.get("quantity") ?? 0),
      low_stock_threshold: Number.isNaN(normalizedThreshold)
        ? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD
        : normalizedThreshold,
      expiration_date: ((formData.get("expiration_date") as string) || "").trim() || null,
      location: ((formData.get("location") as string) || "").trim() || null
    };
    if (!payload.name) {
      setError("Le nom est obligatoire.");
      return;
    }
    if (payload.quantity < 0) {
      setError("La quantité doit être positive.");
      return;
    }
    if (payload.low_stock_threshold < 0) {
      setError("Le seuil de stock doit être positif ou nul.");
      return;
    }
    setMessage(null);
    setError(null);
    if (formMode === "edit" && selected) {
      await updateItem.mutateAsync({ id: selected.id, payload });
    } else {
      await createItem.mutateAsync(payload);
    }
    event.currentTarget.reset();
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Pharmacie</h2>
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

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="overflow-hidden rounded-lg border border-slate-800">
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
                      {canEdit ? (
                        <td className="px-4 py-3 text-xs text-slate-200">
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setSelected(item);
                                setFormMode("edit");
                              }}
                              className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                              title={`Modifier la fiche de ${item.name}`}
                            >
                              Modifier
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

        {canEdit ? (
          <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-white">
              {formMode === "edit" ? "Modifier l'article" : "Ajouter un article"}
            </h3>
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
                  name="name"
                  defaultValue={formValues.name}
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
                  name="dosage"
                  defaultValue={formValues.dosage ?? ""}
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
                  name="packaging"
                  defaultValue={formValues.packaging ?? ""}
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
                  name="barcode"
                  defaultValue={formValues.barcode ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Code-barres associé (facultatif)"
                  inputMode="text"
                  pattern="[\x20-\x7E]*"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="pharmacy-quantity">
                  Quantité
                </label>
                <input
                  id="pharmacy-quantity"
                  name="quantity"
                  type="number"
                  min={0}
                  defaultValue={formValues.quantity}
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
                  name="low_stock_threshold"
                  type="number"
                  min={0}
                  defaultValue={formValues.low_stock_threshold}
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
                  name="expiration_date"
                  type="date"
                  defaultValue={formValues.expiration_date ?? ""}
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
                  name="location"
                  defaultValue={formValues.location ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Emplacement de stockage (armoire, pièce...)"
                />
              </div>
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
          </aside>
        ) : null}
      </div>

      <PharmacyOrdersPanel canEdit={canEdit} />
    </section>
  );
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


import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../../lib/api";
import { resolveMediaUrl } from "../../lib/media";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

interface VehicleItem {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  documentation_url: string | null;
  tutorial_url: string | null;
  qr_token: string | null;
  image_url: string | null;
}

interface VehicleCategory {
  id: number;
  name: string;
}

interface ResourceDraft {
  documentation_url: string;
  tutorial_url: string;
}

export function VehicleQrManagerPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"vehicle" | "name">("vehicle");
  const [drafts, setDrafts] = useState<Record<number, ResourceDraft>>({});
  const [feedback, setFeedback] = useState<string | null>(null);

  const collator = useMemo(() => new Intl.Collator("fr", { sensitivity: "base" }), []);

  const { data: vehicles = [] } = useQuery({
    queryKey: ["vehicle-categories"],
    queryFn: async () => {
      const response = await api.get<VehicleCategory[]>("/vehicle-inventory/categories/");
      return response.data;
    }
  });

  const { data: items = [], isLoading, error } = useQuery({
    queryKey: ["vehicle-items"],
    queryFn: async () => {
      const response = await api.get<VehicleItem[]>("/vehicle-inventory/");
      return response.data;
    }
  });

  useEffect(() => {
    const nextDrafts: Record<number, ResourceDraft> = {};
    items.forEach((item) => {
      nextDrafts[item.id] = {
        documentation_url: item.documentation_url ?? "",
        tutorial_url: item.tutorial_url ?? ""
      };
    });
    setDrafts(nextDrafts);
  }, [items]);

  const vehicleLookup = useMemo(() => {
    const map = new Map<number, string>();
    vehicles.forEach((vehicle) => map.set(vehicle.id, vehicle.name));
    return map;
  }, [vehicles]);

  const getVehicleName = useCallback(
    (item: VehicleItem) => {
      if (!item.category_id) return "Sans véhicule";
      return vehicleLookup.get(item.category_id) ?? "Sans véhicule";
    },
    [vehicleLookup]
  );

  const filteredItems = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => {
      const vehicleName = getVehicleName(item);
      return (
        item.name.toLowerCase().includes(term) ||
        item.sku.toLowerCase().includes(term) ||
        vehicleName.toLowerCase().includes(term)
      );
    });
  }, [getVehicleName, items, search]);

  const sortedItems = useMemo(() => {
    const itemsToSort = [...filteredItems];
    itemsToSort.sort((a, b) => {
      const vehicleA = getVehicleName(a);
      const vehicleB = getVehicleName(b);

      if (sortBy === "vehicle") {
        const byVehicle = collator.compare(vehicleA, vehicleB);
        if (byVehicle !== 0) return byVehicle;
        return collator.compare(a.name, b.name);
      }

      const byName = collator.compare(a.name, b.name);
      if (byName !== 0) return byName;
      return collator.compare(vehicleA, vehicleB);
    });
    return itemsToSort;
  }, [collator, filteredItems, getVehicleName, sortBy]);

  const updateResources = useMutation({
    mutationFn: async (payload: { itemId: number; documentation_url: string; tutorial_url: string }) => {
      await api.put(`/vehicle-inventory/${payload.itemId}`, {
        documentation_url: payload.documentation_url || null,
        tutorial_url: payload.tutorial_url || null
      });
    },
    onSuccess: async () => {
      setFeedback("Liens mis à jour avec succès.");
      await queryClient.invalidateQueries({ queryKey: ["vehicle-items"] });
    },
    onError: (mutationError) => {
      let message = "Impossible d'enregistrer les liens pour cet article.";
      if (isAxiosError(mutationError)) {
        const detail = mutationError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setFeedback(message);
    }
  });

  const downloadQr = useMutation({
    mutationFn: async (payload: { itemId: number; regenerate: boolean }) => {
      const response = await api.get(`/vehicle-inventory/${payload.itemId}/qr-code`, {
        responseType: "blob",
        params: { regenerate: payload.regenerate }
      });
      const blobUrl = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `vehicule-${payload.itemId}-qr.png`;
      link.click();
      window.URL.revokeObjectURL(blobUrl);
      return response.headers["x-vehicle-qr-token"] as string | undefined;
    },
    onSuccess: async (token) => {
      if (token) {
        await queryClient.invalidateQueries({ queryKey: ["vehicle-items"] });
      }
    },
    onError: (mutationError) => {
      let message = "Échec de la génération du QR code.";
      if (isAxiosError(mutationError)) {
        const detail = mutationError.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setFeedback(message);
    }
  });

  const handleUpdateDraft = (itemId: number, field: keyof ResourceDraft, value: string) => {
    setDrafts((previous) => ({
      ...previous,
      [itemId]: {
        ...previous[itemId],
        [field]: value
      }
    }));
  };

  const handleSave = (itemId: number) => {
    const draft = drafts[itemId];
    if (!draft) return;
    updateResources.mutate({
      itemId,
      documentation_url: draft.documentation_url,
      tutorial_url: draft.tutorial_url
    });
  };

  const buildShareUrl = (item: VehicleItem) => {
    if (!item.qr_token) return null;
    return `${API_BASE_URL}/vehicle-inventory/public/${item.qr_token}/page`;
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">QR codes véhicules</h1>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Gérez les liens publics associés au matériel véhicule et exportez un QR code prêt à être affiché.
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Rechercher par nom, référence ou véhicule"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 sm:max-w-sm"
          />
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span className="whitespace-nowrap">Trier par</span>
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as typeof sortBy)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="vehicle">Véhicule (A → Z)</option>
              <option value="name">Nom du matériel</option>
            </select>
          </label>
        </div>
      </div>

      {feedback && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          {feedback}
        </p>
      )}

      {error && (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">
          Impossible de charger les données de l'inventaire.
        </p>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">Chargement...</p>
      ) : sortedItems.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Aucun matériel véhicule ne correspond à votre recherche.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sortedItems.map((item) => {
            const draft = drafts[item.id] ?? { documentation_url: "", tutorial_url: "" };
            const shareUrl = buildShareUrl(item);
            const vehicleName = getVehicleName(item);
            const cover = resolveMediaUrl(item.image_url);
            return (
              <article
                key={item.id}
                className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="flex items-start gap-3">
                  <div className="h-16 w-16 overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
                    {cover ? (
                      <img src={cover} alt={item.name} className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">Aucune image</div>
                    )}
                  </div>
                  <div className="flex-1">
                    <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{vehicleName}</p>
                    <h2 className="text-base font-semibold text-slate-900 dark:text-white">{item.name}</h2>
                    <p className="text-xs text-slate-500 dark:text-slate-400">Réf. {item.sku}</p>
                  </div>
                </div>

                <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  Documentation
                  <input
                    type="url"
                    value={draft.documentation_url}
                    onChange={(event) => handleUpdateDraft(item.id, "documentation_url", event.target.value)}
                    placeholder="https://..."
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>

                <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  Tutoriel
                  <input
                    type="url"
                    value={draft.tutorial_url}
                    onChange={(event) => handleUpdateDraft(item.id, "tutorial_url", event.target.value)}
                    placeholder="https://..."
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>

                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <button
                    type="button"
                    onClick={() => handleSave(item.id)}
                    disabled={updateResources.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {updateResources.isPending ? "Enregistrement..." : "Enregistrer les liens"}
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadQr.mutate({ itemId: item.id, regenerate: false })}
                    className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    Télécharger le QR
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadQr.mutate({ itemId: item.id, regenerate: true })}
                    className="inline-flex items-center gap-2 rounded-md border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-700 transition hover:bg-amber-50 dark:border-amber-400/60 dark:text-amber-200 dark:hover:bg-amber-500/10"
                  >
                    Régénérer le lien
                  </button>
                  {shareUrl ? (
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(shareUrl);
                          setFeedback("Lien copié dans le presse-papiers.");
                        } catch (clipError) {
                          setFeedback("Impossible de copier le lien.");
                        }
                      }}
                      className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      Copier le lien
                    </button>
                  ) : (
                    <span className="text-xs text-amber-600 dark:text-amber-300">
                      Le QR sera disponible après la première génération.
                    </span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

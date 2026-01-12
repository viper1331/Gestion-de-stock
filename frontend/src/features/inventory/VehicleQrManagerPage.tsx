import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../../lib/api";
import { getCachedApiBaseUrl } from "../../lib/apiConfig";
import { resolveMediaUrl } from "../../lib/media";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

type VehicleType = string;

interface VehicleItem {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  vehicle_type: VehicleType | null;
  shared_file_url: string | null;
  documentation_url: string | null;
  tutorial_url: string | null;
  qr_token: string | null;
  image_url: string | null;
  show_in_qr: boolean;
}

interface VehicleItemGroup {
  key: string;
  items: VehicleItem[];
  representative: VehicleItem;
}

interface VehicleCategory {
  id: number;
  name: string;
  vehicle_type: VehicleType | null;
}

interface ResourceDraft {
  shared_file_url: string;
  documentation_url: string;
  tutorial_url: string;
  show_in_qr: boolean;
}

export function VehicleQrManagerPage() {
  const queryClient = useQueryClient();
  const moduleTitle = useModuleTitle("vehicle_qrcodes");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"vehicle" | "name">("vehicle");
  const [drafts, setDrafts] = useState<Record<string, ResourceDraft>>({});
  const [selectedMaterialName, setSelectedMaterialName] = useState<string | null>(null);
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

  const itemsWithVehicle = useMemo(
    () => items.filter((item) => item.category_id !== null),
    [items]
  );

  const materialGroups = useMemo(() => {
    const groups = new Map<string, VehicleItemGroup>();

    const getGroupKey = (item: VehicleItem) => `${item.category_id ?? "none"}::${item.name.trim().toLowerCase()}`;

    itemsWithVehicle.forEach((item) => {
      const key = getGroupKey(item);
      const existing = groups.get(key);
      if (existing) {
        existing.items.push(item);
      } else {
        groups.set(key, {
          key,
          items: [item],
          representative: item
        });
      }
    });

    return Array.from(groups.values());
  }, [itemsWithVehicle]);

  useEffect(() => {
    setDrafts((previous) => {
      const next: Record<string, ResourceDraft> = {};
      materialGroups.forEach((group) => {
        const representative = group.representative;
        next[group.key] =
          previous[group.key] ?? {
            shared_file_url: representative.shared_file_url ?? "",
            documentation_url: representative.documentation_url ?? "",
            tutorial_url: representative.tutorial_url ?? "",
            show_in_qr: representative.show_in_qr
          };
      });
      return next;
    });
  }, [materialGroups]);

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

  const materialTypes = useMemo(() => {
    const unique = new Set<string>();
    materialGroups.forEach((group) => unique.add(group.representative.name));
    return Array.from(unique).sort((a, b) => collator.compare(a, b));
  }, [collator, materialGroups]);

  const filteredItems = useMemo(() => {
    const filteredByMaterial = selectedMaterialName
      ? materialGroups.filter((group) => group.representative.name === selectedMaterialName)
      : materialGroups;
    const term = search.trim().toLowerCase();
    if (!term) return filteredByMaterial;
    return filteredByMaterial.filter((group) => {
      const vehicleName = getVehicleName(group.representative);
      const skus = group.items.map((item) => item.sku.toLowerCase()).join(" ");
      return (
        group.representative.name.toLowerCase().includes(term) ||
        skus.includes(term) ||
        vehicleName.toLowerCase().includes(term)
      );
    });
  }, [getVehicleName, materialGroups, search, selectedMaterialName]);

  const sortedItems = useMemo(() => {
    const itemsToSort = [...filteredItems];
    itemsToSort.sort((a, b) => {
      const vehicleA = getVehicleName(a.representative);
      const vehicleB = getVehicleName(b.representative);

      if (sortBy === "vehicle") {
        const byVehicle = collator.compare(vehicleA, vehicleB);
        if (byVehicle !== 0) return byVehicle;
        return collator.compare(a.representative.name, b.representative.name);
      }

      const byName = collator.compare(a.representative.name, b.representative.name);
      if (byName !== 0) return byName;
      return collator.compare(vehicleA, vehicleB);
    });
    return itemsToSort;
  }, [collator, filteredItems, getVehicleName, sortBy]);

  const groupedItems = useMemo(() => {
    const groups = new Map<string, VehicleItemGroup[]>();
    sortedItems.forEach((group) => {
      const vehicleName = getVehicleName(group.representative);
      const existing = groups.get(vehicleName);
      if (existing) {
        existing.push(group);
      } else {
        groups.set(vehicleName, [group]);
      }
    });

    return Array.from(groups.entries()).sort(([vehicleA], [vehicleB]) =>
      collator.compare(vehicleA, vehicleB)
    );
  }, [collator, getVehicleName, sortedItems]);

  const updateResources = useMutation({
    mutationFn: async (payload: {
      itemIds: number[];
      shared_file_url: string;
      documentation_url: string;
      tutorial_url: string;
      show_in_qr: boolean;
    }) => {
      await Promise.all(
        payload.itemIds.map((itemId) =>
          api.put(`/vehicle-inventory/${itemId}`, {
            shared_file_url: payload.shared_file_url || null,
            documentation_url: payload.documentation_url || null,
            tutorial_url: payload.tutorial_url || null,
            show_in_qr: payload.show_in_qr
          })
        )
      );
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

  const handleUpdateDraft = (groupKey: string, patch: Partial<ResourceDraft>) => {
    setDrafts((previous) => {
      const current = previous[groupKey] ?? {
        shared_file_url: "",
        documentation_url: "",
        tutorial_url: "",
        show_in_qr: true
      };
      return {
        ...previous,
        [groupKey]: {
          ...current,
          ...patch
        }
      };
    });
  };

  const handleSave = (group: VehicleItemGroup) => {
    const draft = drafts[group.key];
    if (!draft) return;
    updateResources.mutate({
      itemIds: group.items.map((item) => item.id),
      shared_file_url: draft.shared_file_url,
      documentation_url: draft.documentation_url,
      tutorial_url: draft.tutorial_url,
      show_in_qr: draft.show_in_qr
    });
  };

  const buildShareUrl = (item: VehicleItem) => {
    if (!item.qr_token) return null;
    if (item.shared_file_url) return item.shared_file_url;
    const base = getCachedApiBaseUrl();
    return `${base}/vehicle-inventory/public/${item.qr_token}/page`;
  };

  const renderItemCard = (group: VehicleItemGroup) => {
    const primaryItem = group.representative;
    const draft =
      drafts[group.key] ?? {
        shared_file_url: "",
        documentation_url: "",
        tutorial_url: "",
        show_in_qr: true
      };
    const shareUrl = buildShareUrl(primaryItem);
    const vehicleName = getVehicleName(primaryItem);
    const cover = resolveMediaUrl(primaryItem.image_url);
    const hasVehicle = Boolean(primaryItem.category_id);
    const isHidden = !draft.show_in_qr;

    return (
      <article
        key={group.key}
        className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex items-start gap-3">
          <div className="h-16 w-16 overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
            {cover ? (
              <img src={cover} alt={group.representative.name} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">Aucune image</div>
            )}
          </div>
          <div className="flex-1">
            <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{vehicleName}</p>
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">{primaryItem.name}</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">Réf. {primaryItem.sku}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {isHidden ? (
                <span className="inline-flex items-center rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700 dark:bg-slate-800 dark:text-slate-100">
                  QR masqué
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-200">
                  QR visible
                </span>
              )}
            </div>
          </div>
        </div>

        <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Fichier associé (OneDrive)
          <AppTextInput
            type="url"
            value={draft.shared_file_url}
            onChange={(event) => handleUpdateDraft(group.key, { shared_file_url: event.target.value })}
            placeholder="https://onedrive.live.com/..."
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
          <p className="mt-1 text-xs font-normal text-slate-500 dark:text-slate-400">
            Saisissez le lien partagé du fichier hébergé dans OneDrive. Il sera utilisé pour la redirection du QR code.
          </p>
        </label>

        <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Documentation
          <AppTextInput
            type="url"
            value={draft.documentation_url}
            onChange={(event) => handleUpdateDraft(group.key, { documentation_url: event.target.value })}
            placeholder="https://..."
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>

        <label className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Tutoriel
          <AppTextInput
            type="url"
            value={draft.tutorial_url}
            onChange={(event) => handleUpdateDraft(group.key, { tutorial_url: event.target.value })}
            placeholder="https://..."
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-950/40">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-semibold text-slate-800 dark:text-slate-100">Visibilité du QR</p>
              <p className="text-xs font-normal text-slate-500 dark:text-slate-400">
                Masquez ce matériel si le QR ne doit plus être consultable par les équipes.
              </p>
            </div>
            <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <span>{draft.show_in_qr ? "Visible" : "Masqué"}</span>
              <AppTextInput
                type="checkbox"
                className="h-4 w-4 rounded border-slate-400 text-indigo-600 focus:ring-indigo-500"
                checked={draft.show_in_qr}
                onChange={(event) => handleUpdateDraft(group.key, { show_in_qr: event.target.checked })}
              />
            </label>
          </div>
          {isHidden && (
            <p className="mt-2 text-xs text-amber-600 dark:text-amber-300">
              Les QR téléchargés renverront un message d'indisponibilité tant que ce matériel reste masqué.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <button
            type="button"
            onClick={() => handleSave(group)}
            disabled={updateResources.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {updateResources.isPending ? "Enregistrement..." : "Enregistrer les liens"}
          </button>
          {hasVehicle ? (
            <>
              <button
                type="button"
                onClick={() => downloadQr.mutate({ itemId: primaryItem.id, regenerate: false })}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Télécharger le QR
              </button>
              <button
                type="button"
                onClick={() => downloadQr.mutate({ itemId: primaryItem.id, regenerate: true })}
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
            </>
          ) : (
            <span className="text-xs text-amber-600 dark:text-amber-300">
              Affectez ce matériel à un véhicule pour générer un QR code.
            </span>
          )}
          {isHidden && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Ce QR ne peut pas être consulté tant que le matériel est masqué.
            </span>
          )}
        </div>
      </article>
    );
  };

  const content = (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">{moduleTitle}</h1>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Gérez les liens publics associés au matériel véhicule et exportez un QR code prêt à être affiché.
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
          <AppTextInput
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Rechercher par nom, référence ou véhicule"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 sm:max-w-sm"
          />
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span className="whitespace-nowrap">Type de matériel</span>
            <select
              value={selectedMaterialName ?? "all"}
              onChange={(event) => {
                const nextValue = event.target.value;
                setSelectedMaterialName(nextValue === "all" ? null : nextValue);
              }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              <option value="all">Tous les types</option>
              {materialTypes.map((material) => (
                <option key={material} value={material}>
                  {material}
                </option>
              ))}
            </select>
          </label>
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
        <div className="space-y-8">
          {groupedItems.map(([vehicleName, vehicleItems]) => (
            <section key={vehicleName} className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{vehicleName}</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {vehicleItems.length} {vehicleItems.length > 1 ? "matériels" : "matériel"}
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {vehicleItems.map(renderItemCard)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "vehicle-qr-main",
      title: moduleTitle,
      permissions: ["vehicle_inventory"],
      required: true,
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      variant: "plain",
      render: () => (
        <EditableBlock id="vehicle-qr-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout pageKey="module:vehicle:qr" blocks={blocks} className="space-y-6" />
  );
}

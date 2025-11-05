import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  MouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import vanIllustration from "../../assets/vehicles/vehicle-van.svg";
import pickupIllustration from "../../assets/vehicles/vehicle-pickup.svg";
import ambulanceIllustration from "../../assets/vehicles/vehicle-ambulance.svg";
import { api } from "../../lib/api";
import { resolveMediaUrl } from "../../lib/media";
import { VehiclePhotosPanel } from "./VehiclePhotosPanel";

interface VehicleViewConfig {
  name: string;
  background_photo_id: number | null;
  background_url: string | null;
}

interface VehicleCategory {
  id: number;
  name: string;
  sizes: string[];
  view_configs?: VehicleViewConfig[] | null;
}

interface VehicleItem {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  size: string | null;
  quantity: number;
  remise_item_id: number | null;
  image_url: string | null;
  position_x: number | null;
  position_y: number | null;
}

interface VehiclePhoto {
  id: number;
  image_url: string;
  uploaded_at: string;
}

interface VehicleFormValues {
  name: string;
  sizes: string[];
}

interface UploadVehicleImagePayload {
  categoryId: number;
  file: File;
}

interface UpdateItemPayload {
  itemId: number;
  categoryId: number | null;
  size: string | null;
  position?: { x: number; y: number } | null;
  successMessage?: string;
}

const VEHICLE_ILLUSTRATIONS = [
  vanIllustration,
  pickupIllustration,
  ambulanceIllustration
];

const DEFAULT_VIEW_LABEL = "VUE PRINCIPALE";

type DraggedItemData = {
  itemId: number;
  offsetX?: number;
  offsetY?: number;
  elementWidth?: number;
  elementHeight?: number;
};

type Feedback = { type: "success" | "error"; text: string };

export function VehicleInventoryPage() {
  const queryClient = useQueryClient();
  const [selectedVehicleId, setSelectedVehicleId] = useState<number | null>(null);
  const [selectedView, setSelectedView] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );
  const [isCreatingVehicle, setIsCreatingVehicle] = useState(false);
  const [vehicleName, setVehicleName] = useState("");
  const [vehicleViewsInput, setVehicleViewsInput] = useState("");
  const [vehicleImageFile, setVehicleImageFile] = useState<File | null>(null);
  const vehicleImageInputRef = useRef<HTMLInputElement | null>(null);

  const {
    data: vehicles = [],
    isLoading: isLoadingVehicles,
    error: vehiclesError
  } = useQuery({
    queryKey: ["vehicle-categories"],
    queryFn: async () => {
      const response = await api.get<VehicleCategory[]>("/vehicle-inventory/categories/");
      return response.data;
    }
  });

  const vehicleFallbackMap = useMemo(() => {
    const map = new Map<number, string>();
    vehicles.forEach((vehicle, index) => {
      map.set(vehicle.id, VEHICLE_ILLUSTRATIONS[index % VEHICLE_ILLUSTRATIONS.length]);
    });
    return map;
  }, [vehicles]);

  const {
    data: items = [],
    isLoading: isLoadingItems,
    error: itemsError
  } = useQuery({
    queryKey: ["vehicle-items"],
    queryFn: async () => {
      const response = await api.get<VehicleItem[]>("/vehicle-inventory/");
      return response.data;
    }
  });

  const { data: vehiclePhotos = [] } = useQuery({
    queryKey: ["vehicle-photos"],
    queryFn: async () => {
      const response = await api.get<VehiclePhoto[]>("/vehicle-inventory/photos/");
      return response.data;
    }
  });

  const updateItemLocation = useMutation({
    mutationFn: async ({ itemId, categoryId, size, position }: UpdateItemPayload) => {
      const payload: Record<string, unknown> = {
        category_id: categoryId,
        size
      };
      if (position) {
        payload.position_x = position.x;
        payload.position_y = position.y;
      } else if (position === null) {
        payload.position_x = null;
        payload.position_y = null;
      }
      await api.put(`/vehicle-inventory/${itemId}`, payload);
    },
    onSuccess: (_, variables) => {
      if (variables.successMessage) {
        setFeedback({ type: "success", text: variables.successMessage });
        return;
      }
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Le matériel a été associé à ${vehicleName}.`
          : "Le matériel a été retiré du véhicule."
      });
    },
    onError: () => {
      setFeedback({ type: "error", text: "Impossible d'enregistrer la position." });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-items"] });
    }
  });

  const updateViewBackground = useMutation({
    mutationFn: async ({
      categoryId,
      name,
      photoId
    }: {
      categoryId: number;
      name: string;
      photoId: number | null;
    }) => {
      const response = await api.put<VehicleViewConfig>(
        `/vehicle-inventory/categories/${categoryId}/views/background`,
        {
          name,
          photo_id: photoId
        }
      );
      return response.data;
    },
    onSuccess: async (_, variables) => {
      setFeedback({
        type: "success",
        text: variables.photoId
          ? "Photo de fond enregistrée."
          : "Photo de fond retirée."
      });
      await queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] });
    },
    onError: () => {
      setFeedback({
        type: "error",
        text: "Impossible de mettre à jour la photo de fond."
      });
    }
  });

  const pushFeedback = (entry: Feedback) => {
    setFeedback(entry);
  };
  const createVehicle = useMutation({
    mutationFn: async ({ name, sizes }: VehicleFormValues) => {
      const response = await api.post<VehicleCategory>("/vehicle-inventory/categories/", {
        name,
        sizes
      });
      return response.data;
    },
    onError: () => {
      setFeedback({ type: "error", text: "Impossible de créer ce véhicule." });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] });
    }
  });

  const uploadVehicleImage = useMutation({
    mutationFn: async ({ categoryId, file }: UploadVehicleImagePayload) => {
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.post<VehicleCategory>(
        `/vehicle-inventory/categories/${categoryId}/image`,
        formData,
        {
          headers: { "Content-Type": "multipart/form-data" }
        }
      );
      return response.data;
    },
    onError: () => {
      setFeedback({ type: "error", text: "Impossible de téléverser la photo du véhicule." });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] });
    }
  });

  const selectedVehicle = useMemo(
    () => vehicles.find((vehicle) => vehicle.id === selectedVehicleId) ?? null,
    [vehicles, selectedVehicleId]
  );

  const selectedVehicleFallback = useMemo(() => {
    if (!selectedVehicle) {
      return undefined;
    }
    return vehicleFallbackMap.get(selectedVehicle.id);
  }, [selectedVehicle, vehicleFallbackMap]);

  const vehicleViews = useMemo(() => getVehicleViews(selectedVehicle), [selectedVehicle]);

  const normalizedSelectedView = useMemo(
    () => (selectedView ? normalizeViewName(selectedView) : null),
    [selectedView]
  );

  const selectedViewConfig = useMemo(() => {
    if (!selectedVehicle?.view_configs || !normalizedSelectedView) {
      return null;
    }
    return (
      selectedVehicle.view_configs.find(
        (view) => normalizeViewName(view.name) === normalizedSelectedView
      ) ?? null
    );
  }, [selectedVehicle?.view_configs, normalizedSelectedView]);

  useEffect(() => {
    if (!selectedVehicle) {
      setSelectedView(null);
      return;
    }

    if (selectedView && vehicleViews.includes(selectedView)) {
      return;
    }

    setSelectedView(vehicleViews[0] ?? DEFAULT_VIEW_LABEL);
  }, [selectedVehicle, selectedView, vehicleViews]);

  const vehicleItems = useMemo(
    () => items.filter((item) => item.category_id === selectedVehicle?.id),
    [items, selectedVehicle?.id]
  );

  const itemsForSelectedView = useMemo(
    () =>
      vehicleItems.filter((item) => {
        if (!normalizedSelectedView) {
          return false;
        }
        return normalizeViewName(item.size) === normalizedSelectedView;
      }),
    [vehicleItems, normalizedSelectedView]
  );

  const itemsWaitingAssignment = useMemo(
    () => vehicleItems.filter((item) => !item.size),
    [vehicleItems]
  );

  const itemsInOtherViews = useMemo(
    () =>
      vehicleItems.filter((item) => {
        if (!item.size) {
          return false;
        }
        if (!normalizedSelectedView) {
          return false;
        }
        return normalizeViewName(item.size) !== normalizedSelectedView;
      }),
    [vehicleItems, normalizedSelectedView]
  );

  const availableItems = useMemo(
    () => items.filter((item) => item.category_id === null),
    [items]
  );

  const isLoading =
    isLoadingVehicles ||
    isLoadingItems ||
    updateItemLocation.isPending ||
    createVehicle.isPending ||
    uploadVehicleImage.isPending;

  const clearVehicleImageSelection = () => {
    setVehicleImageFile(null);
    if (vehicleImageInputRef.current) {
      vehicleImageInputRef.current.value = "";
    }
  };

  const handleVehicleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setVehicleImageFile(file);
  };

  const handleCreateVehicle = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = vehicleName.trim();
    if (!trimmedName) {
      setFeedback({ type: "error", text: "Veuillez indiquer un nom de véhicule." });
      return;
    }

    const parsedViews = normalizeVehicleViewsInput(vehicleViewsInput);

    try {
      const createdVehicle = await createVehicle.mutateAsync({
        name: trimmedName,
        sizes: parsedViews
      });
      let finalVehicle = createdVehicle;
      if (vehicleImageFile) {
        finalVehicle = await uploadVehicleImage.mutateAsync({
          categoryId: createdVehicle.id,
          file: vehicleImageFile
        });
      }
      setFeedback({
        type: "success",
        text: `Le véhicule "${finalVehicle.name}" a été créé.`
      });
      setVehicleName("");
      setVehicleViewsInput("");
      clearVehicleImageSelection();
      setIsCreatingVehicle(false);
      setSelectedVehicleId(finalVehicle.id);
      setSelectedView(null);
    } catch {
      // handled in mutation callbacks
    }
  };

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                Inventaire véhicules
              </h1>
              <p className="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
                Visualisez chaque véhicule sous forme de vue interactive et organisez son matériel
                coffre par coffre grâce au glisser-déposer.
              </p>
            </div>
            {isCreatingVehicle ? (
              <form
                onSubmit={handleCreateVehicle}
                className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
              >
                <div className="flex flex-col gap-2 sm:flex-row">
                  <label className="flex-1 space-y-1" htmlFor="vehicle-name">
                    <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                      Nom du véhicule
                    </span>
                    <input
                      id="vehicle-name"
                      type="text"
                      value={vehicleName}
                      onChange={(event) => setVehicleName(event.target.value)}
                      placeholder="Ex. VSAV 1"
                      className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                      disabled={createVehicle.isPending}
                      required
                    />
                  </label>
                  <label className="flex-1 space-y-1" htmlFor="vehicle-views">
                    <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                      Vues (optionnel)
                    </span>
                    <input
                      id="vehicle-views"
                      type="text"
                      value={vehicleViewsInput}
                      onChange={(event) => setVehicleViewsInput(event.target.value)}
                      placeholder="Vue principale, Coffre gauche, Coffre droit"
                      className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                      disabled={createVehicle.isPending}
                    />
                  </label>
                </div>
                <label className="block space-y-1" htmlFor="vehicle-image">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Photo du véhicule (optionnel)
                  </span>
                  <input
                    id="vehicle-image"
                    ref={vehicleImageInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleVehicleImageChange}
                    disabled={createVehicle.isPending || uploadVehicleImage.isPending}
                    className="block w-full text-xs text-slate-600 file:mr-4 file:cursor-pointer file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-slate-700 hover:file:bg-slate-300 dark:text-slate-200 dark:file:bg-slate-700 dark:file:text-slate-100 dark:hover:file:bg-slate-600"
                  />
                  {vehicleImageFile ? (
                    <span className="block text-xs text-slate-500 dark:text-slate-400">
                      {vehicleImageFile.name}
                    </span>
                  ) : null}
                </label>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Saisissez les différentes vues séparées par des virgules. Si aucun nom n'est renseigné, la vue "{DEFAULT_VIEW_LABEL}" sera utilisée.
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setIsCreatingVehicle(false);
                      setVehicleName("");
                      setVehicleViewsInput("");
                      clearVehicleImageSelection();
                    }}
                    className="inline-flex items-center justify-center rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                    disabled={createVehicle.isPending || uploadVehicleImage.isPending}
                  >
                    Annuler
                  </button>
                  <button
                    type="submit"
                    className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    disabled={createVehicle.isPending || uploadVehicleImage.isPending}
                  >
                    {createVehicle.isPending || uploadVehicleImage.isPending
                      ? "Création..."
                      : "Créer le véhicule"}
                  </button>
                </div>
              </form>
            ) : null}
          </div>
          <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={() =>
                setIsCreatingVehicle((previous) => {
                  if (previous) {
                    setVehicleName("");
                    setVehicleViewsInput("");
                    clearVehicleImageSelection();
                  }
                  return !previous;
                })
              }
              className="inline-flex items-center gap-2 rounded-full border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-600 transition hover:border-indigo-300 hover:text-indigo-700 dark:border-indigo-500/40 dark:text-indigo-200 dark:hover:border-indigo-400 dark:hover:text-white"
            >
              <span aria-hidden>＋</span>
              {isCreatingVehicle ? "Fermer le formulaire" : "Nouveau véhicule"}
            </button>
            {selectedVehicle && (
              <button
                type="button"
                onClick={() => setSelectedVehicleId(null)}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
              >
                <span aria-hidden>←</span>
                Retour aux véhicules
              </button>
            )}
          </div>
        </div>
        {feedback && (
          <p
            className={clsx("mt-4 rounded-lg px-3 py-2 text-sm", {
              "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200":
                feedback.type === "success",
              "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-200":
                feedback.type === "error"
            })}
          >
            {feedback.text}
          </p>
        )}
        {(vehiclesError || itemsError) && (
          <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">
            Impossible de charger les données de l'inventaire véhicule.
          </p>
        )}
        {isLoading && (
          <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
            Chargement des données...
          </p>
        )}
      </header>

      {!selectedVehicle && (
        <section className="grid gap-6 lg:grid-cols-3">
          {vehicles.map((vehicle) => (
            <VehicleCard
              key={vehicle.id}
              vehicle={vehicle}
              fallbackIllustration={
                vehicleFallbackMap.get(vehicle.id) ?? VEHICLE_ILLUSTRATIONS[0]
              }
              onClick={() => setSelectedVehicleId(vehicle.id)}
            />
          ))}
          {vehicles.length === 0 && !isLoading && (
            <p className="col-span-full rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              Aucun véhicule n'a encore été configuré. Ajoutez des véhicules depuis les paramètres
              de l'inventaire pour commencer l'organisation du matériel.
            </p>
          )}
        </section>
      )}

      {selectedVehicle && selectedView && (
        <section className="space-y-6">
          <VehicleHeader
            vehicle={selectedVehicle}
            itemsCount={vehicleItems.length}
            fallbackIllustration={selectedVehicleFallback}
          />

          <VehicleViewSelector
            views={vehicleViews}
            selectedView={selectedView}
            onSelect={setSelectedView}
          />

          <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
            <VehicleCompartment
              title={selectedView ?? DEFAULT_VIEW_LABEL}
              description="Déposez ici le matériel pour l'associer à cette vue du véhicule."
              items={itemsForSelectedView}
              viewConfig={selectedViewConfig}
              availablePhotos={vehiclePhotos}
              onDropItem={(itemId, position, options) =>
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: normalizedSelectedView ?? DEFAULT_VIEW_LABEL,
                  position,
                  successMessage: options?.isReposition ? "Position enregistrée." : undefined
                })
              }
              onRemoveItem={(itemId) =>
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: null,
                  position: null
                })
              }
              onItemFeedback={pushFeedback}
              onBackgroundChange={(photoId) =>
                updateViewBackground.mutate({
                  categoryId: selectedVehicle.id,
                  name: normalizedSelectedView ?? DEFAULT_VIEW_LABEL,
                  photoId
                })
              }
              isUpdatingBackground={updateViewBackground.isPending}
            />

            <aside className="space-y-6">
              <VehicleItemsPanel
                title="Matériel dans les autres vues"
                description="Faites glisser un équipement vers la vue courante pour le déplacer."
                emptyMessage="Aucun matériel n'est stocké dans les autres vues pour ce véhicule."
                items={itemsInOtherViews}
                onItemFeedback={pushFeedback}
              />

              <VehicleItemsPanel
                title="Matériel en attente d'affectation"
                description="Ces éléments sont liés au véhicule mais pas à une vue précise."
                emptyMessage="Tout le matériel est déjà affecté à une vue."
                items={itemsWaitingAssignment}
                onItemFeedback={pushFeedback}
              />

              <DroppableLibrary
                items={availableItems}
                onDropItem={(itemId) =>
                  updateItemLocation.mutate({
                    itemId,
                    categoryId: null,
                    size: null,
                    position: null
                  })
                }
                onRemoveFromVehicle={(itemId) =>
                  updateItemLocation.mutate({
                    itemId,
                    categoryId: null,
                    size: null,
                    position: null
                  })
                }
                onItemFeedback={pushFeedback}
              />
            </aside>
          </div>
          <VehiclePhotosPanel />
        </section>
      )}
    </div>
  );
}

interface VehicleCardProps {
  vehicle: VehicleCategory;
  fallbackIllustration: string;
  onClick: () => void;
}

function VehicleCard({ vehicle, fallbackIllustration, onClick }: VehicleCardProps) {
  const imageSource = vehicle.image_url ?? fallbackIllustration;
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-left shadow-sm transition hover:-translate-y-1 hover:border-slate-300 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600"
    >
      <div className="relative h-44 w-full bg-slate-50 dark:bg-slate-800">
        <img
          src={imageSource}
          alt={`Illustration du véhicule ${vehicle.name}`}
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-900/30 via-transparent" />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-5">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {vehicle.name}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {vehicle.sizes.length > 0
              ? `${vehicle.sizes.length} vue${vehicle.sizes.length > 1 ? "s" : ""} configurée${
                  vehicle.sizes.length > 1 ? "s" : ""
                }`
              : "Vue principale uniquement"}
          </p>
        </div>
        <span className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 transition group-hover:text-blue-700 dark:text-blue-400 dark:group-hover:text-blue-300">
          Ouvrir l'organisation
          <span aria-hidden>→</span>
        </span>
      </div>
    </button>
  );
}

interface VehicleHeaderProps {
  vehicle: VehicleCategory;
  itemsCount: number;
  fallbackIllustration?: string;
}

function VehicleHeader({ vehicle, itemsCount, fallbackIllustration }: VehicleHeaderProps) {
  const imageSource = vehicle.image_url ?? fallbackIllustration ?? VEHICLE_ILLUSTRATIONS[0];
  return (
    <div className="flex flex-col gap-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900 md:flex-row md:items-center md:justify-between">
      <div className="flex items-center gap-4">
        <div className="hidden h-20 w-36 overflow-hidden rounded-xl bg-slate-100 shadow-inner dark:bg-slate-800 md:block">
          <img src={imageSource} alt="Vue du véhicule" className="h-full w-full object-cover" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            {vehicle.name}
          </h2>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {itemsCount} matériel{itemsCount > 1 ? "s" : ""} associé{itemsCount > 1 ? "s" : ""}.
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
        {getVehicleViews(vehicle).map((view) => (
          <span key={view} className="rounded-full bg-slate-100 px-3 py-1 dark:bg-slate-800">
            {view}
          </span>
        ))}
      </div>
    </div>
  );
}

interface VehicleViewSelectorProps {
  views: string[];
  selectedView: string;
  onSelect: (view: string) => void;
}

function VehicleViewSelector({ views, selectedView, onSelect }: VehicleViewSelectorProps) {
  return (
    <div className="flex flex-wrap gap-3">
      {views.map((view) => (
        <button
          key={view}
          type="button"
          onClick={() => onSelect(view)}
          className={clsx(
            "rounded-full border px-4 py-2 text-sm font-medium transition",
            view === selectedView
              ? "border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-400 dark:bg-blue-950/50 dark:text-blue-200"
              : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
          )}
        >
          {view}
        </button>
      ))}
    </div>
  );
}

interface VehicleCompartmentProps {
  title: string;
  description: string;
  items: VehicleItem[];
  viewConfig: VehicleViewConfig | null;
  availablePhotos: VehiclePhoto[];
  onDropItem: (
    itemId: number,
    position: { x: number; y: number },
    options?: { isReposition?: boolean }
  ) => void;
  onRemoveItem: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
  onBackgroundChange: (photoId: number | null) => void;
  isUpdatingBackground: boolean;
}

function VehicleCompartment({
  title,
  description,
  items,
  viewConfig,
  availablePhotos,
  onDropItem,
  onRemoveItem,
  onItemFeedback,
  onBackgroundChange,
  isUpdatingBackground
}: VehicleCompartmentProps) {
  const [isHovering, setIsHovering] = useState(false);
  const boardRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();

  const uploadBackground = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.post<VehiclePhoto>("/vehicle-inventory/photos/", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      return response.data;
    },
    onSuccess: async (photo) => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-photos"] });
      onBackgroundChange(photo.id);
      onItemFeedback({ type: "success", text: "Photo importée et appliquée." });
    },
    onError: () => {
      onItemFeedback({ type: "error", text: "Impossible d'importer la photo." });
    }
  });

  const selectedBackgroundId = viewConfig?.background_photo_id ?? null;
  const selectedBackground = selectedBackgroundId
    ? availablePhotos.find((photo) => photo.id === selectedBackgroundId) ?? null
    : null;
  const isProcessingBackground = isUpdatingBackground || uploadBackground.isPending;

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setIsHovering(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!boardRef.current) {
      return;
    }
    const nextTarget = event.relatedTarget as Node | null;
    if (nextTarget && boardRef.current.contains(nextTarget)) {
      return;
    }
    setIsHovering(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsHovering(false);
    const data = readDraggedItemData(event);
    if (!data) {
      return;
    }
    const rect = boardRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    const elementWidth = data.elementWidth ?? 0;
    const elementHeight = data.elementHeight ?? 0;
    const offsetX = data.offsetX ?? elementWidth / 2;
    const offsetY = data.offsetY ?? elementHeight / 2;
    const pointerX = event.clientX - rect.left;
    const pointerY = event.clientY - rect.top;
    const centerX = pointerX - offsetX + elementWidth / 2;
    const centerY = pointerY - offsetY + elementHeight / 2;
    const position = {
      x: clamp(centerX / rect.width, 0, 1),
      y: clamp(centerY / rect.height, 0, 1)
    };
    const isReposition = items.some((item) => item.id === data.itemId);
    onDropItem(data.itemId, position, { isReposition });
  };

  const handleBackgroundUploadChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      onItemFeedback({ type: "error", text: "Seules les images sont autorisées." });
      event.target.value = "";
      return;
    }
    uploadBackground.mutate(file);
    event.target.value = "";
  };

  const handleOpenBackgroundUpload = () => {
    fileInputRef.current?.click();
  };

  const handleSelectBackground = (photoId: number) => {
    if (photoId === selectedBackgroundId) {
      return;
    }
    onBackgroundChange(photoId);
  };

  const handleClearBackground = () => {
    if (!selectedBackgroundId) {
      return;
    }
    onBackgroundChange(null);
  };

  const boardStyle = viewConfig?.background_url
    ? {
        backgroundImage: `url(${viewConfig.background_url})`,
        backgroundSize: "cover",
        backgroundPosition: "center"
      }
    : {
        backgroundImage:
          "linear-gradient(135deg, rgba(148,163,184,0.15) 25%, transparent 25%), linear-gradient(-135deg, rgba(148,163,184,0.15) 25%, transparent 25%), linear-gradient(135deg, transparent 75%, rgba(148,163,184,0.15) 75%), linear-gradient(-135deg, transparent 75%, rgba(148,163,184,0.15) 75%)",
        backgroundSize: "32px 32px",
        backgroundPosition: "0 0, 16px 0, 16px -16px, 0px 16px",
        backgroundColor: "rgba(148,163,184,0.08)"
      };

  return (
    <div>
      <div
        className={clsx(
          "flex h-full flex-col gap-6 rounded-2xl border-2 border-dashed bg-white p-6 text-slate-600 shadow-sm transition dark:bg-slate-900",
          isHovering
            ? "border-blue-400 bg-blue-50/60 text-blue-700 dark:border-blue-500 dark:bg-blue-950/40 dark:text-blue-200"
            : "border-slate-300 dark:border-slate-700"
        )}
      >
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">{description}</p>
          </div>
          <div className="flex w-full flex-col gap-3 text-xs md:w-80">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-600 dark:text-slate-300">Photo de fond</span>
              <button
                type="button"
                onClick={handleClearBackground}
                disabled={isProcessingBackground || !selectedBackgroundId}
                className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
              >
                Retirer
              </button>
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
              {selectedBackground ? (
                <img
                  src={selectedBackground.image_url}
                  alt="Photo de fond sélectionnée"
                  className="h-36 w-full object-cover"
                />
              ) : (
                <div className="flex h-36 items-center justify-center px-4 text-center text-[11px] text-slate-500 dark:text-slate-400">
                  Aucune photo sélectionnée pour cette vue.
                </div>
              )}
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleBackgroundUploadChange}
            />

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleOpenBackgroundUpload}
                disabled={isProcessingBackground}
                className="rounded-full border border-dashed border-blue-400 px-4 py-1.5 text-[11px] font-semibold text-blue-600 transition hover:border-blue-500 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-blue-500 dark:text-blue-300 dark:hover:border-blue-400 dark:hover:text-blue-200"
              >
                {uploadBackground.isPending ? "Téléversement en cours..." : "Importer une photo"}
              </button>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              {availablePhotos.map((photo) => (
                <button
                  key={photo.id}
                  type="button"
                  onClick={() => handleSelectBackground(photo.id)}
                  disabled={isProcessingBackground}
                  className={clsx(
                    "relative overflow-hidden rounded-lg border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    selectedBackgroundId === photo.id
                      ? "border-blue-500 ring-2 ring-blue-200"
                      : "border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-500"
                  )}
                >
                  <span className="sr-only">Sélectionner cette photo comme fond</span>
                  <img src={photo.image_url} alt={`Photo du véhicule ${photo.id}`} className="h-20 w-full object-cover" />
                  {selectedBackgroundId === photo.id ? (
                    <div className="absolute inset-0 bg-blue-500/20" aria-hidden />
                  ) : null}
                </button>
              ))}
              {availablePhotos.length === 0 && (
                <p className="col-span-full rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-[11px] text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  Ajoutez une photo pour personnaliser cette vue.
                </p>
              )}
            </div>

            <span className="text-[11px] text-slate-500 dark:text-slate-400">
              {availablePhotos.length > 0
                ? "Cliquez sur une miniature pour l'utiliser comme fond et positionnez précisément votre matériel."
                : "Importez une photo de l'intérieur du véhicule pour définir un fond personnalisé."}
            </span>
          </div>
        </div>

        <div
          ref={boardRef}
          className={clsx(
            "relative min-h-[320px] w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 transition dark:border-slate-700 dark:bg-slate-800",
            isHovering &&
              "border-blue-400 ring-4 ring-blue-200/60 dark:border-blue-500 dark:ring-blue-900/50"
          )}
          style={boardStyle}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-slate-900/5 via-transparent to-white/10 dark:from-slate-950/20 dark:to-slate-900/10" />
          {items.map((item) => (
            <VehicleItemMarker key={item.id} item={item} />
          ))}
          {items.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center text-sm font-medium text-slate-600 dark:text-slate-300">
              Glissez un équipement sur la photo pour enregistrer son emplacement.
            </div>
          )}
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400">
          Faites glisser un matériel depuis la bibliothèque vers la zone ci-dessus pour l'affecter et le positionner. Vous pouvez déplacer les marqueurs existants pour affiner l'emplacement.
        </p>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              onRemove={() => onRemoveItem(item.id)}
              onFeedback={onItemFeedback}
              onUpdatePosition={(position) => onDropItem(item.id, position, { isReposition: true })}
            />
          ))}
          {items.length === 0 && (
            <p className="col-span-full rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              Déposez un matériel depuis la bibliothèque pour l'affecter à ce coffre.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

interface VehicleItemMarkerProps {
  item: VehicleItem;
}

function VehicleItemMarker({ item }: VehicleItemMarkerProps) {
  const positionX = clamp(item.position_x ?? 0.5, 0, 1);
  const positionY = clamp(item.position_y ?? 0.5, 0, 1);

  return (
    <button
      type="button"
      className="group absolute -translate-x-1/2 -translate-y-1/2 cursor-move rounded-lg bg-white/90 px-3 py-2 text-xs font-medium text-slate-700 shadow-md backdrop-blur-sm transition hover:scale-105 dark:bg-slate-900/80 dark:text-slate-200"
      style={{ left: `${positionX * 100}%`, top: `${positionY * 100}%` }}
      draggable
      onDragStart={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        event.dataTransfer.setData(
          "application/json",
          JSON.stringify({
            itemId: item.id,
            offsetX: event.clientX - rect.left,
            offsetY: event.clientY - rect.top,
            elementWidth: rect.width,
            elementHeight: rect.height
          })
        );
        event.dataTransfer.effectAllowed = "move";
      }}
      title={`${item.name} (Qté : ${item.quantity})`}
    >
      <span className="block text-xs font-semibold text-slate-700 dark:text-slate-100">
        {item.name}
      </span>
      <span className="block text-[10px] text-slate-500 dark:text-slate-300">
        Qté : {item.quantity}
      </span>
    </button>
  );
}

interface VehicleItemsPanelProps {
  title: string;
  description: string;
  emptyMessage: string;
  items: VehicleItem[];
  onItemFeedback?: (feedback: Feedback) => void;
}

function VehicleItemsPanel({
  title,
  description,
  emptyMessage,
  items,
  onItemFeedback
}: VehicleItemsPanelProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{description}</p>
      <div className="mt-4 space-y-3">
        {items.map((item) => (
          <ItemCard key={item.id} item={item} onFeedback={onItemFeedback} />
        ))}
        {items.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {emptyMessage}
          </p>
        )}
      </div>
    </div>
  );
}

interface DroppableLibraryProps {
  items: VehicleItem[];
  onDropItem: (itemId: number) => void;
  onRemoveFromVehicle: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
}

function DroppableLibrary({
  items,
  onDropItem,
  onRemoveFromVehicle,
  onItemFeedback
}: DroppableLibraryProps) {
  const [isHovering, setIsHovering] = useState(false);

  return (
    <div
      className={clsx(
        "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition dark:border-slate-700 dark:bg-slate-900",
        isHovering &&
          "border-blue-400 bg-blue-50/60 text-blue-700 dark:border-blue-500 dark:bg-blue-950/50 dark:text-blue-200"
      )}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setIsHovering(true);
      }}
      onDragLeave={() => setIsHovering(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsHovering(false);
        const data = readDraggedItemData(event);
        if (data) {
          onDropItem(data.itemId);
        }
      }}
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Bibliothèque de matériel
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Glissez un élément depuis cette bibliothèque vers une vue pour l'affecter ou vers la
            bibliothèque pour le retirer du véhicule.
          </p>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            onRemove={() => onRemoveFromVehicle(item.id)}
            onFeedback={onItemFeedback}
          />
        ))}
          {items.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            Aucun matériel disponible. Gérez vos articles depuis l'inventaire remises pour les rendre
            disponibles ici.
          </p>
        )}
      </div>
    </div>
  );
}

interface ItemCardProps {
  item: VehicleItem;
  onRemove?: () => void;
  onFeedback?: (feedback: Feedback) => void;
  onUpdatePosition?: (position: { x: number; y: number }) => void;
}

function ItemCard({ item, onRemove, onFeedback, onUpdatePosition }: ItemCardProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isEditingPosition, setIsEditingPosition] = useState(false);
  const [draftPosition, setDraftPosition] = useState(() => ({
    x: Math.round(clamp((item.position_x ?? 0.5) * 100, 0, 100)),
    y: Math.round(clamp((item.position_y ?? 0.5) * 100, 0, 100))
  }));

  useEffect(() => {
    if (isEditingPosition) {
      return;
    }
    setDraftPosition({
      x: Math.round(clamp((item.position_x ?? 0.5) * 100, 0, 100)),
      y: Math.round(clamp((item.position_y ?? 0.5) * 100, 0, 100))
    });
  }, [item.position_x, item.position_y, isEditingPosition]);

  const uploadImage = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      await api.post(`/vehicle-inventory/${item.id}/image`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
    },
    onSuccess: async () => {
      onFeedback?.({ type: "success", text: "Image du matériel mise à jour." });
      await queryClient.invalidateQueries({ queryKey: ["vehicle-items"] });
    },
    onError: () => {
      onFeedback?.({ type: "error", text: "Impossible d'enregistrer l'image du matériel." });
    }
  });

  const removeImage = useMutation({
    mutationFn: async () => {
      await api.delete(`/vehicle-inventory/${item.id}/image`);
    },
    onSuccess: async () => {
      onFeedback?.({ type: "success", text: "Image du matériel supprimée." });
      await queryClient.invalidateQueries({ queryKey: ["vehicle-items"] });
    },
    onError: () => {
      onFeedback?.({ type: "error", text: "Impossible de supprimer l'image du matériel." });
    }
  });

  const isUpdatingImage = uploadImage.isPending || removeImage.isPending;

  const openFileDialog = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      onFeedback?.({ type: "error", text: "Seules les images sont autorisées." });
      event.target.value = "";
      return;
    }
    uploadImage.mutate(file);
    event.target.value = "";
  };

  const handleRemoveImage = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    removeImage.mutate();
  };

  const handleRemoveItem = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onRemove?.();
  };

  const canEditPosition = Boolean(onUpdatePosition);
  const currentPositionX = Math.round(clamp((item.position_x ?? 0.5) * 100, 0, 100));
  const currentPositionY = Math.round(clamp((item.position_y ?? 0.5) * 100, 0, 100));

  const handleTogglePositionEditor = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!canEditPosition) {
      return;
    }
    setIsEditingPosition((previous) => !previous);
  };

  const handlePositionSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!onUpdatePosition) {
      setIsEditingPosition(false);
      return;
    }
    onUpdatePosition({ x: draftPosition.x / 100, y: draftPosition.y / 100 });
    setIsEditingPosition(false);
  };

  const handlePositionCancel = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsEditingPosition(false);
    setDraftPosition({ x: currentPositionX, y: currentPositionY });
  };

  const handlePositionInputChange = (axis: "x" | "y") => (event: ChangeEvent<HTMLInputElement>) => {
    event.stopPropagation();
    const rawValue = Number(event.target.value);
    const sanitized = Number.isNaN(rawValue) ? 0 : rawValue;
    setDraftPosition((previous) => ({
      ...previous,
      [axis]: clamp(sanitized, 0, 100)
    }));
  };

  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600"
      draggable={!isEditingPosition}
      onDragStart={(event) => {
        if (isEditingPosition) {
          event.preventDefault();
          return;
        }
        const rect = event.currentTarget.getBoundingClientRect();
        event.dataTransfer.setData(
          "application/json",
          JSON.stringify({
            itemId: item.id,
            offsetX: event.clientX - rect.left,
            offsetY: event.clientY - rect.top,
            elementWidth: rect.width,
            elementHeight: rect.height
          })
        );
        event.dataTransfer.effectAllowed = "move";
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={handleFileChange}
      />
      <div className="flex items-center gap-3">
        <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
          {hasImage ? (
            <img
              src={imageUrl ?? undefined}
              alt={`Illustration de ${item.name}`}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="px-2 text-center text-[11px] text-slate-500 dark:text-slate-400">
              Aucune image
            </span>
          )}
        </div>
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{item.name}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">SKU : {item.sku}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Qté : {item.quantity}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={openFileDialog}
          disabled={isUpdatingImage}
          className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-70 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
        >
          {hasImage ? "Changer l'image" : "Ajouter une image"}
        </button>
        {hasImage ? (
          <button
            type="button"
            onClick={handleRemoveImage}
            disabled={isUpdatingImage}
            className="rounded-full border border-rose-300 px-3 py-1 text-xs font-medium text-rose-600 transition hover:border-rose-400 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-70 dark:border-rose-500/70 dark:text-rose-200 dark:hover:border-rose-400 dark:hover:text-rose-100"
          >
            Supprimer l'image
          </button>
        ) : null}
        {onRemove ? (
          <button
            type="button"
            onClick={handleRemoveItem}
            className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
          >
            Retirer
          </button>
        ) : null}
        {isUpdatingImage ? (
          <span className="text-[11px] text-slate-500 dark:text-slate-400">Enregistrement…</span>
        ) : null}
      </div>
      {canEditPosition ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600 dark:border-slate-600/70 dark:bg-slate-800/40 dark:text-slate-200">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-slate-600 dark:text-slate-200">
              Position : X {currentPositionX}% · Y {currentPositionY}%
            </span>
            <button
              type="button"
              onClick={handleTogglePositionEditor}
              className="rounded-full border border-slate-300 px-3 py-1 font-medium transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-500 dark:hover:border-slate-400"
            >
              {isEditingPosition ? "Fermer" : "Ajuster"}
            </button>
          </div>
          {isEditingPosition ? (
            <form className="mt-3 space-y-3" onSubmit={handlePositionSubmit}>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[11px] font-semibold text-slate-600 dark:text-slate-200">
                    Axe horizontal (X)
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={draftPosition.x}
                    onChange={handlePositionInputChange("x")}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                  />
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">Pourcentage de la largeur</span>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[11px] font-semibold text-slate-600 dark:text-slate-200">
                    Axe vertical (Y)
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={draftPosition.y}
                    onChange={handlePositionInputChange("y")}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                  />
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">Pourcentage de la hauteur</span>
                </label>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  onClick={handlePositionCancel}
                  className="rounded-full border border-slate-300 px-3 py-1 font-medium transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-500 dark:hover:border-slate-400"
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  className="rounded-full border border-blue-500 bg-blue-500 px-3 py-1 font-semibold text-white transition hover:bg-blue-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  Enregistrer
                </button>
              </div>
            </form>
          ) : (
            <p className="mt-2 text-[10px] text-slate-500 dark:text-slate-400">
              Cliquez sur « Ajuster » pour saisir des coordonnées précises (0 à 100&nbsp;%).
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function readDraggedItemData(event: DragEvent<HTMLElement>): DraggedItemData | null {
  const rawData = event.dataTransfer.getData("application/json");
  if (!rawData) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawData) as Partial<DraggedItemData>;
    if (typeof parsed.itemId === "number") {
      return {
        itemId: parsed.itemId,
        offsetX: typeof parsed.offsetX === "number" ? parsed.offsetX : undefined,
        offsetY: typeof parsed.offsetY === "number" ? parsed.offsetY : undefined,
        elementWidth: typeof parsed.elementWidth === "number" ? parsed.elementWidth : undefined,
        elementHeight: typeof parsed.elementHeight === "number" ? parsed.elementHeight : undefined
      };
    }
  } catch {
    return null;
  }

  return null;
}

function normalizeVehicleViewsInput(rawInput: string): string[] {
  const entries = rawInput
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .map((entry) => normalizeViewName(entry));

  const uniqueEntries = Array.from(new Set(entries));

  return uniqueEntries.length > 0 ? uniqueEntries : [DEFAULT_VIEW_LABEL];
}

function getVehicleViews(vehicle: VehicleCategory | null): string[] {
  if (!vehicle) {
    return [DEFAULT_VIEW_LABEL];
  }

  if (vehicle.view_configs && vehicle.view_configs.length > 0) {
    const normalized = vehicle.view_configs
      .map((config) => normalizeViewName(config.name))
      .filter((entry, index, array) => array.indexOf(entry) === index);
    return normalized.length > 0 ? normalized : [DEFAULT_VIEW_LABEL];
  }

  const sanitized = vehicle.sizes
    .map((entry) => normalizeViewName(entry))
    .filter((entry, index, array) => array.indexOf(entry) === index);

  return sanitized.length > 0 ? sanitized : [DEFAULT_VIEW_LABEL];
}

function normalizeViewName(view: string | null): string {
  if (view && view.trim().length > 0) {
    return view.trim().toUpperCase();
  }
  return DEFAULT_VIEW_LABEL;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

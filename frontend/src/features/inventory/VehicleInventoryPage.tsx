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

interface VehicleCategory {
  id: number;
  name: string;
  sizes: string[];
  image_url: string | null;
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
}

const VEHICLE_ILLUSTRATIONS = [
  vanIllustration,
  pickupIllustration,
  ambulanceIllustration
];

const DEFAULT_VIEW_LABEL = "Vue principale";

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

  const updateItemLocation = useMutation({
    mutationFn: async ({ itemId, categoryId, size }: UpdateItemPayload) => {
      await api.put(`/vehicle-inventory/${itemId}`, {
        category_id: categoryId,
        size
      });
    },
    onSuccess: (_, variables) => {
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
        if (!selectedView) {
          return false;
        }
        return normalizeViewName(item.size) === selectedView;
      }),
    [vehicleItems, selectedView]
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
        if (!selectedView) {
          return false;
        }
        return normalizeViewName(item.size) !== selectedView;
      }),
    [vehicleItems, selectedView]
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
              title={selectedView}
              description="Déposez ici le matériel pour l'associer à cette vue du véhicule."
              items={itemsForSelectedView}
              onDropItem={(itemId) =>
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: selectedView
                })
              }
              onRemoveItem={(itemId) =>
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: null
                })
              }
              onItemFeedback={pushFeedback}
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
                  updateItemLocation.mutate({ itemId, categoryId: selectedVehicle.id, size: selectedView })
                }
                onRemoveFromVehicle={(itemId) =>
                  updateItemLocation.mutate({ itemId, categoryId: null, size: null })
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
  onDropItem: (itemId: number) => void;
  onRemoveItem: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
}

function VehicleCompartment({
  title,
  description,
  items,
  onDropItem,
  onRemoveItem,
  onItemFeedback
}: VehicleCompartmentProps) {
  const [isHovering, setIsHovering] = useState(false);

  return (
    <div>
      <div
        className={clsx(
          "flex h-full flex-col gap-4 rounded-2xl border-2 border-dashed bg-white p-6 text-slate-600 shadow-sm transition dark:bg-slate-900",
          isHovering
            ? "border-blue-400 bg-blue-50/60 text-blue-700 dark:border-blue-500 dark:bg-blue-950/50 dark:text-blue-200"
            : "border-slate-300 dark:border-slate-700"
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
          const itemId = readDraggedItemId(event);
          if (itemId !== null) {
            onDropItem(itemId);
          }
        }}
      >
        <div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">{description}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              onRemove={() => onRemoveItem(item.id)}
              onFeedback={onItemFeedback}
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
        const itemId = readDraggedItemId(event);
        if (itemId !== null) {
          onDropItem(itemId);
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
}

function ItemCard({ item, onRemove, onFeedback }: ItemCardProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const imageUrl = resolveMediaUrl(item.image_url);
  const hasImage = Boolean(imageUrl);

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

  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(
          "application/json",
          JSON.stringify({ itemId: item.id })
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
    </div>
  );
}

function readDraggedItemId(event: DragEvent<HTMLDivElement>): number | null {
  const rawData = event.dataTransfer.getData("application/json");
  if (!rawData) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawData) as { itemId?: unknown };
    if (typeof parsed.itemId === "number") {
      return parsed.itemId;
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
    .filter((entry) => entry.length > 0);

  const uniqueEntries = Array.from(new Set(entries));

  return uniqueEntries.length > 0 ? uniqueEntries : [DEFAULT_VIEW_LABEL];
}

function getVehicleViews(vehicle: VehicleCategory | null): string[] {
  if (!vehicle) {
    return [DEFAULT_VIEW_LABEL];
  }

  const sanitized = vehicle.sizes
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);

  return sanitized.length > 0 ? sanitized : [DEFAULT_VIEW_LABEL];
}

function normalizeViewName(view: string | null): string {
  if (view && view.trim().length > 0) {
    return view.trim();
  }
  return DEFAULT_VIEW_LABEL;
}

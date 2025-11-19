import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { isAxiosError } from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import vanIllustration from "../../assets/vehicles/vehicle-van.svg";
import pickupIllustration from "../../assets/vehicles/vehicle-pickup.svg";
import ambulanceIllustration from "../../assets/vehicles/vehicle-ambulance.svg";
import { api } from "../../lib/api";
import { resolveMediaUrl } from "../../lib/media";
import { usePersistentBoolean } from "../../hooks/usePersistentBoolean";
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
  image_url: string | null;
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
  remise_quantity: number | null;
  image_url: string | null;
  position_x: number | null;
  position_y: number | null;
  lot_id: number | null;
  lot_name: string | null;
  show_in_qr: boolean;
}

interface RemiseLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  image_url: string | null;
  item_count: number;
  total_quantity: number;
}

interface RemiseLotItem {
  id: number;
  lot_id: number;
  remise_item_id: number;
  quantity: number;
  remise_name: string;
  remise_sku: string;
  available_quantity: number;
}

interface RemiseLotWithItems extends RemiseLot {
  items: RemiseLotItem[];
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

interface UpdateVehiclePayload {
  categoryId: number;
  name: string;
  sizes: string[];
}

interface UpdateItemPayload {
  itemId: number;
  categoryId: number | null;
  size: string | null;
  position?: { x: number; y: number } | null;
  quantity?: number;
  successMessage?: string;
}

const VEHICLE_ILLUSTRATIONS = [
  vanIllustration,
  pickupIllustration,
  ambulanceIllustration
];

const DEFAULT_VIEW_LABEL = "VUE PRINCIPALE";

type DraggedItemData = {
  itemId?: number;
  categoryId?: number | null;
  remiseItemId?: number | null;
  assignedLotItemIds?: number[];
  offsetX?: number;
  offsetY?: number;
  elementWidth?: number;
  elementHeight?: number;
  lotId?: number | null;
  lotName?: string | null;
};

type Feedback = { type: "success" | "error"; text: string };

type PointerTarget = { x: number; y: number };
type PointerTargetMap = Record<string, PointerTarget>;

function collectPointerTargetsPayload(): PointerTargetMap {
  if (typeof window === "undefined") {
    return {};
  }
  const collected: PointerTargetMap = {};
  const prefix = "vehicleInventory:itemsPanel:";
  const suffix = ":pointer-targets";

  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (!key || !key.startsWith(prefix) || !key.endsWith(suffix)) {
      continue;
    }
    const parsed = readPointerTargetsFromStorage(key);
    Object.entries(parsed).forEach(([markerKey, target]) => {
      if (
        target &&
        typeof target.x === "number" &&
        typeof target.y === "number"
      ) {
        const clampedX = Math.min(1, Math.max(0, target.x));
        const clampedY = Math.min(1, Math.max(0, target.y));
        collected[markerKey] = { x: clampedX, y: clampedY };
      }
    });
  }

  return collected;
}

function readPointerTargetsFromStorage(storageKey: string): PointerTargetMap {
  if (typeof window === "undefined") {
    return {};
  }
  try {
    const rawValue = window.localStorage.getItem(storageKey);
    if (!rawValue) {
      return {};
    }
    const parsed = JSON.parse(rawValue) as PointerTargetMap;
    if (parsed && typeof parsed === "object") {
      return parsed;
    }
  } catch {
    return {};
  }
  return {};
}

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
  const [isEditingVehicle, setIsEditingVehicle] = useState(false);
  const [editedVehicleName, setEditedVehicleName] = useState("");
  const [editedVehicleViewsInput, setEditedVehicleViewsInput] = useState("");
  const [editedVehicleImageFile, setEditedVehicleImageFile] = useState<File | null>(null);
  const editedVehicleImageInputRef = useRef<HTMLInputElement | null>(null);
  const [isBackgroundPanelVisible, setIsBackgroundPanelVisible] = useState(true);

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

  const { data: remiseLots = [], isLoading: isLoadingLots } = useQuery({
    queryKey: ["remise-lots-with-items"],
    queryFn: async () => {
      const response = await api.get<RemiseLotWithItems[]>("/remise-inventory/lots/with-items");
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
    mutationFn: async ({ itemId, categoryId, size, position, quantity }: UpdateItemPayload) => {
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
      if (typeof quantity === "number") {
        payload.quantity = quantity;
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

  const assignItemToVehicle = useMutation({
    mutationFn: async ({
      itemId,
      categoryId,
      size,
      position
    }: {
      itemId: number;
      categoryId: number;
      size: string;
      position: { x: number; y: number };
    }) => {
      const template = items.find((entry) => entry.id === itemId);
      if (!template) {
        throw new Error("Matériel introuvable.");
      }
      if (template.remise_item_id == null) {
        throw new Error("Ce matériel n'est pas lié à l'inventaire remises.");
      }
      if ((template.remise_quantity ?? 0) <= 0) {
        throw new Error("Stock insuffisant en remise.");
      }
      const response = await api.post<VehicleItem>("/vehicle-inventory/", {
        name: template.name,
        sku: template.sku,
        category_id: categoryId,
        size,
        quantity: 1,
        position_x: position.x,
        position_y: position.y,
        remise_item_id: template.remise_item_id
      });
      return response.data;
    },
    onSuccess: (_, variables) => {
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Un exemplaire a été affecté à ${vehicleName}.`
          : "Le matériel a été affecté au véhicule."
      });
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.data?.detail) {
        setFeedback({ type: "error", text: error.response.data.detail });
        return;
      }
      setFeedback({
        type: "error",
        text: "Impossible d'affecter ce matériel au véhicule."
      });
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

  const assignLotToVehicle = useMutation({
    mutationFn: async ({
      lot,
      categoryId,
      view,
      position
    }: {
      lot: RemiseLotWithItems;
      categoryId: number;
      view: string;
      position: { x: number; y: number } | null;
    }) => {
      const created: VehicleItem[] = [];
      const normalizedView = normalizeViewName(view);
      const basePosition = position ?? { x: 0.5, y: 0.5 };
      const distributedPositions = generateLotPositions(basePosition, lot.items.length);
      for (const [index, item] of lot.items.entries()) {
        const coords = distributedPositions[index] ?? null;
        const response = await api.post<VehicleItem>("/vehicle-inventory/", {
          name: item.remise_name,
          sku: item.remise_sku,
          category_id: categoryId,
          size: normalizedView,
          quantity: item.quantity,
          position_x: coords?.x ?? null,
          position_y: coords?.y ?? null,
          remise_item_id: item.remise_item_id,
          lot_id: lot.id
        });
        created.push(response.data);
      }
      return created;
    },
    onSuccess: async (_, variables) => {
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      const lotName = variables.lot?.name ?? null;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Le lot${lotName ? ` ${lotName}` : ""} a été ajouté au véhicule ${vehicleName}.`
          : "Le lot a été ajouté au véhicule."
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.data?.detail) {
        setFeedback({ type: "error", text: error.response.data.detail });
        return;
      }
      setFeedback({
        type: "error",
        text: "Impossible d'ajouter ce lot au véhicule."
      });
    }
  });

  const removeLotFromVehicle = useMutation({
    mutationFn: async ({ lotId, categoryId }: { lotId: number; categoryId: number }) => {
      await api.post(`/vehicle-inventory/lots/${lotId}/unassign`, {
        category_id: categoryId
      });
    },
    onSuccess: async (_, variables) => {
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      const lotName = remiseLots.find((lot) => lot.id === variables.lotId)?.name ?? null;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Le lot${lotName ? ` ${lotName}` : ""} a été retiré du véhicule ${vehicleName}.`
          : "Le lot a été retiré du véhicule."
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
        queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ]);
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.data?.detail) {
        setFeedback({ type: "error", text: error.response.data.detail });
        return;
      }
      setFeedback({
        type: "error",
        text: "Impossible de retirer ce lot du véhicule."
      });
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

  const updateVehicle = useMutation({
    mutationFn: async ({ categoryId, name, sizes }: UpdateVehiclePayload) => {
      const response = await api.put<VehicleCategory>(
        `/vehicle-inventory/categories/${categoryId}`,
        {
          name,
          sizes
        }
      );
      return response.data;
    },
    onError: () => {
      setFeedback({ type: "error", text: "Impossible de mettre à jour ce véhicule." });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] });
    }
  });

  const deleteVehicle = useMutation({
    mutationFn: async (categoryId: number) => {
      await api.delete(`/vehicle-inventory/categories/${categoryId}`);
    },
    onSuccess: () => {
      setFeedback({ type: "success", text: "Véhicule supprimé." });
      setSelectedVehicleId(null);
      setSelectedView(null);
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
    },
    onError: () => {
      setFeedback({ type: "error", text: "Impossible de supprimer ce véhicule." });
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-categories"] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] })
      ]);
    }
  });

  const exportInventoryPdf = useMutation({
    mutationFn: async () => {
      const pointerTargets = collectPointerTargetsPayload();
      const response = await api.post(
        "/vehicle-inventory/export/pdf",
        { pointer_targets: pointerTargets },
        {
          responseType: "arraybuffer"
        }
      );
      return response.data as ArrayBuffer;
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
      link.download = `inventaire_vehicules_${timestamp}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      setFeedback({ type: "success", text: "L'inventaire des véhicules a été exporté." });
    },
    onError: (error) => {
      let message = "Une erreur est survenue lors de l'export du PDF.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setFeedback({ type: "error", text: message });
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
    if (selectedVehicleId === null) {
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
    }
  }, [selectedVehicleId]);

  const normalizedSelectedView = useMemo(
    () => (selectedView ? normalizeViewName(selectedView) : null),
    [selectedView]
  );

  const backgroundPanelStorageKey = useMemo(() => {
    const vehicleIdentifier = selectedVehicle?.id ? `vehicle-${selectedVehicle.id}` : "no-vehicle";
    const viewIdentifier = normalizeViewName(normalizedSelectedView).replace(/\s+/g, "-");
    return `vehicleInventory:backgroundPanel:${vehicleIdentifier}:${viewIdentifier}`;
  }, [selectedVehicle?.id, normalizedSelectedView]);

  const itemsPanelStorageKey = useMemo(() => {
    const vehicleIdentifier = selectedVehicle?.id ? `vehicle-${selectedVehicle.id}` : "no-vehicle";
    const viewIdentifier = normalizeViewName(normalizedSelectedView).replace(/\s+/g, "-");
    return `vehicleInventory:itemsPanel:${vehicleIdentifier}:${viewIdentifier}`;
  }, [selectedVehicle?.id, normalizedSelectedView]);

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

  const lotRemiseItemIds = useMemo(() => {
    const ids = new Set<number>();
    for (const lot of remiseLots) {
      for (const entry of lot.items) {
        ids.add(entry.remise_item_id);
      }
    }
    return ids;
  }, [remiseLots]);

  const availableItems = useMemo(
    () =>
      items.filter((item) => {
        if (item.category_id !== null) {
          return false;
        }
        if (item.lot_id !== null) {
          return false;
        }
        if ((item.remise_quantity ?? 0) <= 0) {
          return false;
        }
        if (item.remise_item_id && lotRemiseItemIds.has(item.remise_item_id)) {
          return false;
        }
        return true;
      }),
    [items, lotRemiseItemIds]
  );

  const availableLots = useMemo(
    () =>
      remiseLots.filter(
        (lot) =>
          lot.items.length > 0 &&
          lot.items.every((item) => item.quantity > 0 && item.available_quantity >= item.quantity)
      ),
    [remiseLots]
  );

  const handleDropLotOnView = (lotId: number, position: { x: number; y: number }) => {
    if (!selectedVehicle) {
      setFeedback({ type: "error", text: "Sélectionnez un véhicule avant d'ajouter un lot." });
      return;
    }
    const lot = availableLots.find((entry) => entry.id === lotId);
    if (!lot) {
      setFeedback({ type: "error", text: "Ce lot n'est plus disponible." });
      return;
    }
    const targetView = normalizedSelectedView ?? DEFAULT_VIEW_LABEL;
    assignLotToVehicle.mutate({ lot, categoryId: selectedVehicle.id, view: targetView, position });
  };

  const findLockedLotItem = (itemId: number) =>
    items.find((entry) => entry.id === itemId && entry.lot_id !== null) ?? null;

  const describeLot = (item: VehicleItem) =>
    item.lot_name ?? (item.lot_id ? `Lot #${item.lot_id}` : "lot");

  const isLoading =
    isLoadingVehicles ||
    isLoadingItems ||
    updateItemLocation.isPending ||
    assignItemToVehicle.isPending ||
    createVehicle.isPending ||
    uploadVehicleImage.isPending;

  const clearVehicleImageSelection = () => {
    setVehicleImageFile(null);
    if (vehicleImageInputRef.current) {
      vehicleImageInputRef.current.value = "";
    }
  };

  const clearEditedVehicleImageSelection = () => {
    setEditedVehicleImageFile(null);
    if (editedVehicleImageInputRef.current) {
      editedVehicleImageInputRef.current.value = "";
    }
  };

  const handleVehicleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setVehicleImageFile(file);
  };

  const handleEditedVehicleImageChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setEditedVehicleImageFile(file);
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

  const handleToggleVehicleEdition = () => {
    if (
      !selectedVehicle ||
      updateVehicle.isPending ||
      deleteVehicle.isPending ||
      uploadVehicleImage.isPending
    ) {
      return;
    }
    if (isEditingVehicle) {
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
      clearEditedVehicleImageSelection();
      return;
    }
    setEditedVehicleName(selectedVehicle.name);
    setEditedVehicleViewsInput(getVehicleViews(selectedVehicle).join(", "));
    clearEditedVehicleImageSelection();
    setIsEditingVehicle(true);
  };

  const handleCancelVehicleEdition = () => {
    if (
      updateVehicle.isPending ||
      uploadVehicleImage.isPending ||
      deleteVehicle.isPending
    ) {
      return;
    }
    setIsEditingVehicle(false);
    setEditedVehicleName("");
    setEditedVehicleViewsInput("");
    clearEditedVehicleImageSelection();
  };

  const handleUpdateVehicle = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedVehicle) {
      return;
    }
    const trimmedName = editedVehicleName.trim();
    if (!trimmedName) {
      setFeedback({ type: "error", text: "Veuillez indiquer un nom de véhicule." });
      return;
    }
    const parsedViews = normalizeVehicleViewsInput(editedVehicleViewsInput);
    try {
      await updateVehicle.mutateAsync({
        categoryId: selectedVehicle.id,
        name: trimmedName,
        sizes: parsedViews
      });
      if (editedVehicleImageFile) {
        await uploadVehicleImage.mutateAsync({
          categoryId: selectedVehicle.id,
          file: editedVehicleImageFile
        });
      }
      setFeedback({ type: "success", text: "Véhicule mis à jour." });
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
      clearEditedVehicleImageSelection();
    } catch {
      // feedback handled in mutation callbacks
    }
  };

  const handleDeleteVehicle = () => {
    if (!selectedVehicle || deleteVehicle.isPending || updateVehicle.isPending) {
      return;
    }
    const confirmation = window.confirm(
      `Voulez-vous vraiment supprimer le véhicule "${selectedVehicle.name}" ? Cette action est irréversible.`
    );
    if (!confirmation) {
      return;
    }
    deleteVehicle.mutate(selectedVehicle.id);
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
              onClick={() => exportInventoryPdf.mutate()}
              disabled={exportInventoryPdf.isPending}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
            >
              {exportInventoryPdf.isPending ? "Export en cours…" : "Exporter en PDF"}
            </button>
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
            onEdit={handleToggleVehicleEdition}
            onDelete={handleDeleteVehicle}
            isEditing={isEditingVehicle}
            isUpdating={updateVehicle.isPending}
            isDeleting={deleteVehicle.isPending}
          />

          {isEditingVehicle ? (
            <form
              onSubmit={handleUpdateVehicle}
              className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
            >
              <div className="flex flex-col gap-2 sm:flex-row">
                <label className="flex-1 space-y-1" htmlFor="edit-vehicle-name">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Nom du véhicule
                  </span>
                  <input
                    id="edit-vehicle-name"
                    type="text"
                    value={editedVehicleName}
                    onChange={(event) => setEditedVehicleName(event.target.value)}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    disabled={
                      updateVehicle.isPending ||
                      deleteVehicle.isPending ||
                      uploadVehicleImage.isPending
                    }
                    required
                  />
                </label>
                <label className="flex-1 space-y-1" htmlFor="edit-vehicle-views">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Vues
                  </span>
                  <input
                    id="edit-vehicle-views"
                    type="text"
                    value={editedVehicleViewsInput}
                    onChange={(event) => setEditedVehicleViewsInput(event.target.value)}
                    placeholder="Vue principale, Coffre gauche, Coffre droit"
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    disabled={
                      updateVehicle.isPending ||
                      deleteVehicle.isPending ||
                      uploadVehicleImage.isPending
                    }
                  />
                </label>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Séparez les différentes vues par des virgules ou des retours à la ligne. La vue "{DEFAULT_VIEW_LABEL}" sera utilisée par défaut si aucune vue n'est fournie.
              </p>
              <label className="block space-y-1" htmlFor="edit-vehicle-image">
                <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                  Photo du véhicule (optionnel)
                </span>
                <input
                  id="edit-vehicle-image"
                  ref={editedVehicleImageInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleEditedVehicleImageChange}
                  disabled={
                    updateVehicle.isPending ||
                    deleteVehicle.isPending ||
                    uploadVehicleImage.isPending
                  }
                  className="block w-full text-xs text-slate-600 file:mr-4 file:cursor-pointer file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-slate-700 hover:file:bg-slate-300 dark:text-slate-200 dark:file:bg-slate-700 dark:file:text-slate-100 dark:hover:file:bg-slate-600"
                />
                {editedVehicleImageFile ? (
                  <span className="block text-xs text-slate-500 dark:text-slate-400">
                    {editedVehicleImageFile.name}
                  </span>
                ) : selectedVehicle?.image_url ? (
                  <span className="block text-xs text-slate-500 dark:text-slate-400">
                    Aucune nouvelle photo sélectionnée. La photo actuelle sera conservée.
                  </span>
                ) : (
                  <span className="block text-xs text-slate-500 dark:text-slate-400">
                    Aucune photo n'est définie pour le moment.
                  </span>
                )}
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleCancelVehicleEdition}
                  className="inline-flex items-center justify-center rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={
                    updateVehicle.isPending ||
                    uploadVehicleImage.isPending ||
                    deleteVehicle.isPending
                  }
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                  disabled={
                    updateVehicle.isPending ||
                    deleteVehicle.isPending ||
                    uploadVehicleImage.isPending
                  }
                >
                  {updateVehicle.isPending ? "Enregistrement..." : "Enregistrer les modifications"}
                </button>
              </div>
            </form>
          ) : null}

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
              onDropItem={(itemId, position, options) => {
                const targetView = normalizedSelectedView ?? DEFAULT_VIEW_LABEL;
                if (options?.sourceCategoryId === null) {
                  assignItemToVehicle.mutate({
                    itemId,
                    categoryId: selectedVehicle.id,
                    size: targetView,
                    position
                  });
                  return;
                }
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: targetView,
                  position,
                  quantity: options?.quantity ?? undefined,
                  successMessage:
                    options?.isReposition && !options?.suppressFeedback
                      ? "Position enregistrée."
                      : undefined
                });
              }}
              onRemoveItem={(itemId) => {
                const lockedItem = findLockedLotItem(itemId);
                if (lockedItem) {
                  pushFeedback({
                    type: "error",
                    text: `Ce matériel appartient au ${describeLot(lockedItem)}. Ajustez le lot depuis la page dédiée.`,
                  });
                  return;
                }
                updateItemLocation.mutate({
                  itemId,
                  categoryId: selectedVehicle.id,
                  size: null,
                  position: null,
                  quantity: 0
                });
              }}
              onItemFeedback={pushFeedback}
              onBackgroundChange={(photoId) =>
                updateViewBackground.mutate({
                  categoryId: selectedVehicle.id,
                  name: normalizedSelectedView ?? DEFAULT_VIEW_LABEL,
                  photoId
                })
              }
              isUpdatingBackground={updateViewBackground.isPending}
              backgroundPanelStorageKey={backgroundPanelStorageKey}
              itemsPanelStorageKey={itemsPanelStorageKey}
              onDropLot={handleDropLotOnView}
            />

            <aside className="space-y-6">
              <VehicleItemsPanel
                title="Matériel dans les autres vues"
                description="Faites glisser un équipement vers la vue courante pour le déplacer."
                emptyMessage="Aucun matériel n'est stocké dans les autres vues pour ce véhicule."
                items={itemsInOtherViews}
                onItemFeedback={pushFeedback}
                storageKey="vehicleInventory:panel:otherViews"
              />

              <VehicleItemsPanel
                title="Matériel en attente d'affectation"
                description="Ces éléments sont liés au véhicule mais pas à une vue précise."
                emptyMessage="Tout le matériel est déjà affecté à une vue."
                items={itemsWaitingAssignment}
                onItemFeedback={pushFeedback}
                storageKey="vehicleInventory:panel:pendingAssignment"
              />

              <DroppableLibrary
                items={availableItems}
                lots={availableLots}
                isLoadingLots={isLoadingLots}
                isAssigningLot={assignLotToVehicle.isPending}
                vehicleName={selectedVehicle?.name ?? null}
                onAssignLot={(lot) => {
                  if (!selectedVehicle) {
                    setFeedback({
                      type: "error",
                      text: "Sélectionnez un véhicule avant d'ajouter un lot."
                    });
                    return;
                  }
                  const targetView = normalizedSelectedView ?? DEFAULT_VIEW_LABEL;
                  assignLotToVehicle.mutate({
                    lot,
                    categoryId: selectedVehicle.id,
                    view: targetView,
                    position: null
                  });
                }}
                onDropItem={(itemId) =>
                  updateItemLocation.mutate({
                    itemId,
                    categoryId: null,
                    size: null,
                    position: null,
                    quantity: 0
                  })
                }
                onDropLot={(lotId, categoryId) =>
                  removeLotFromVehicle.mutate({ lotId, categoryId })
                }
                onRemoveFromVehicle={(itemId) =>
                  updateItemLocation.mutate({
                    itemId,
                    categoryId: null,
                    size: null,
                    position: null,
                    quantity: 0
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
  const [hasImageError, setHasImageError] = useState(false);
  const resolvedImageUrl = resolveMediaUrl(vehicle.image_url);
  useEffect(() => {
    setHasImageError(false);
  }, [resolvedImageUrl]);
  const imageSource =
    !hasImageError && resolvedImageUrl ? resolvedImageUrl : fallbackIllustration;
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
          onError={() => setHasImageError(true)}
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
  onEdit: () => void;
  onDelete: () => void;
  isEditing: boolean;
  isUpdating: boolean;
  isDeleting: boolean;
}

function VehicleHeader({
  vehicle,
  itemsCount,
  fallbackIllustration,
  onEdit,
  onDelete,
  isEditing,
  isUpdating,
  isDeleting
}: VehicleHeaderProps) {
  const [hasImageError, setHasImageError] = useState(false);
  const resolvedImageUrl = resolveMediaUrl(vehicle.image_url);
  useEffect(() => {
    setHasImageError(false);
  }, [resolvedImageUrl]);
  const imageSource =
    !hasImageError && resolvedImageUrl
      ? resolvedImageUrl
      : fallbackIllustration ?? VEHICLE_ILLUSTRATIONS[0];
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <div className="hidden h-20 w-36 overflow-hidden rounded-xl bg-slate-100 shadow-inner dark:bg-slate-800 md:block">
            <img
              src={imageSource}
              alt="Vue du véhicule"
              onError={() => setHasImageError(true)}
              className="h-full w-full object-cover"
            />
          </div>
          <div className="space-y-3">
            <div>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {vehicle.name}
              </h2>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {itemsCount} matériel{itemsCount > 1 ? "s" : ""} associé{itemsCount > 1 ? "s" : ""}.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onEdit}
                disabled={isUpdating || isDeleting}
                className={clsx(
                  "inline-flex items-center justify-center rounded-md border px-3 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60",
                  isEditing
                    ? "border-indigo-300 bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:border-indigo-400/60 dark:bg-indigo-500/10 dark:text-indigo-200 dark:hover:bg-indigo-500/20"
                    : "border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                )}
              >
                {isEditing ? "Fermer l'édition" : "Modifier"}
              </button>
              <button
                type="button"
                onClick={onDelete}
                disabled={isDeleting || isUpdating}
                className="inline-flex items-center justify-center rounded-md border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-600 transition hover:bg-rose-50 dark:border-rose-400/60 dark:text-rose-300 dark:hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isDeleting ? "Suppression..." : "Supprimer"}
              </button>
            </div>
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
    options?: {
      isReposition?: boolean;
      quantity?: number | null;
      sourceCategoryId?: number | null;
      remiseItemId?: number | null;
      suppressFeedback?: boolean;
    }
  ) => void;
  onRemoveItem: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
  onBackgroundChange: (photoId: number | null) => void;
  isUpdatingBackground: boolean;
  backgroundPanelStorageKey: string;
  itemsPanelStorageKey: string;
  onDropLot?: (lotId: number, position: { x: number; y: number }) => void;
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
  isUpdatingBackground,
  backgroundPanelStorageKey,
  itemsPanelStorageKey,
  onDropLot
}: VehicleCompartmentProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isBackgroundPanelVisible, setIsBackgroundPanelVisible] = usePersistentBoolean(
    backgroundPanelStorageKey,
    true
  );
  const [isItemsPanelCollapsed, setIsItemsPanelCollapsed] = usePersistentBoolean(
    itemsPanelStorageKey,
    false
  );
  const [isPointerModeEnabled, setIsPointerModeEnabled] = usePersistentBoolean(
    `${itemsPanelStorageKey}:pointer-mode`,
    false
  );
  const pointerTargetStorageKey = `${itemsPanelStorageKey}:pointer-targets`;
  const [pointerTargets, setPointerTargets] = useState<PointerTargetMap>(() =>
    readPointerTargetsFromStorage(pointerTargetStorageKey)
  );
  useEffect(() => {
    setPointerTargets(readPointerTargetsFromStorage(pointerTargetStorageKey));
  }, [pointerTargetStorageKey]);
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(pointerTargetStorageKey, JSON.stringify(pointerTargets));
    } catch {
      /* ignore storage errors */
    }
  }, [pointerTargets, pointerTargetStorageKey]);
  const updatePointerTargets = useCallback(
    (updater: (previous: PointerTargetMap) => PointerTargetMap) => {
      setPointerTargets((previous) => updater(previous));
    },
    []
  );
  const [pendingPointerKey, setPendingPointerKey] = useState<string | null>(null);
  const isSelectingPointerTarget = pendingPointerKey !== null;
  const boardRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();
  const markerEntries = useMemo(() => buildVehicleMarkerEntries(items), [items]);
  const markerLayouts = useMemo(() => buildMarkerLayoutMap(markerEntries), [markerEntries]);

  useEffect(() => {
    if (!isPointerModeEnabled) {
      setPendingPointerKey(null);
    }
  }, [isPointerModeEnabled]);

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
    if (data.assignedLotItemIds && data.assignedLotItemIds.length > 0) {
      data.assignedLotItemIds.forEach((lotItemId, index) => {
        onDropItem(lotItemId, position, {
          isReposition: true,
          suppressFeedback: index > 0
        });
      });
      return;
    }
    if (data.lotId !== null && data.lotId !== undefined) {
      if (onDropLot) {
        onDropLot(data.lotId, position);
      } else {
        onItemFeedback({
          type: "error",
          text: "Sélectionnez un véhicule avant d'ajouter un lot."
        });
      }
      return;
    }
    if (typeof data.itemId !== "number") {
      return;
    }
    const sourceCategoryId =
      data.categoryId === undefined ? undefined : data.categoryId;
    const isFromLibrary = sourceCategoryId === null;
    const isReposition = items.some((item) => item.id === data.itemId);
    onDropItem(data.itemId, position, {
      isReposition,
      quantity: !isFromLibrary && !isReposition ? 1 : undefined,
      sourceCategoryId: sourceCategoryId ?? null,
      remiseItemId:
        data.remiseItemId === undefined ? undefined : data.remiseItemId ?? null
    });
  };

  const handlePointerTargetRequest = useCallback((markerKey: string) => {
    setPendingPointerKey(markerKey);
  }, []);

  const handlePointerTargetClear = useCallback(
    (markerKey: string) => {
      updatePointerTargets((previous) => {
        if (!previous[markerKey]) {
          return previous;
        }
        const nextTargets = { ...previous };
        delete nextTargets[markerKey];
        return nextTargets;
      });
    },
    [updatePointerTargets]
  );

  const handleCancelPointerSelection = () => {
    setPendingPointerKey(null);
  };

  const handleBoardClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!isPointerModeEnabled || !pendingPointerKey || !boardRef.current) {
      return;
    }
    const rect = boardRef.current.getBoundingClientRect();
    const pointerX = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const pointerY = clamp((event.clientY - rect.top) / rect.height, 0, 1);
    const targetKey = pendingPointerKey;
    updatePointerTargets((previous) => ({
      ...previous,
      [targetKey]: { x: pointerX, y: pointerY }
    }));
    setPendingPointerKey(null);
    onItemFeedback({ type: "success", text: "Point de référence défini." });
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

  const backgroundImageUrl = resolveMediaUrl(viewConfig?.background_url);

  const boardStyle = backgroundImageUrl
    ? {
        backgroundImage: `url(${backgroundImageUrl})`,
        backgroundSize: "contain",
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat"
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
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsBackgroundPanelVisible((current) => !current)}
                  aria-expanded={isBackgroundPanelVisible}
                  className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
                >
                  {isBackgroundPanelVisible ? "Masquer" : "Afficher"}
                </button>
                <button
                  type="button"
                  onClick={handleClearBackground}
                  disabled={isProcessingBackground || !selectedBackgroundId}
                  className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
                >
                  Retirer
                </button>
              </div>
            </div>

            {isBackgroundPanelVisible ? (
              <>
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800">
                  {selectedBackground ? (
                    <img
                      src={resolveMediaUrl(selectedBackground.image_url) ?? undefined}
                      alt="Photo de fond sélectionnée"
                      className="h-36 w-full object-contain"
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
                  {availablePhotos.map((photo) => {
                    const photoUrl = resolveMediaUrl(photo.image_url);
                    return (
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
                        <img
                          src={photoUrl ?? undefined}
                          alt={`Photo du véhicule ${photo.id}`}
                          className="h-20 w-full object-contain"
                        />
                        {selectedBackgroundId === photo.id ? (
                          <div className="absolute inset-0 bg-blue-500/20" aria-hidden />
                        ) : null}
                      </button>
                    );
                  })}
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
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-300 px-4 py-3 text-[11px] text-slate-500 dark:border-slate-600 dark:text-slate-400">
                Cette section est masquée. Cliquez sur « Afficher » pour la rouvrir.
              </div>
            )}
          </div>
        </div>

        <div
          ref={boardRef}
          className={clsx(
            "relative min-h-[320px] w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 transition dark:border-slate-700 dark:bg-slate-800",
            isHovering &&
              "border-blue-400 ring-4 ring-blue-200/60 dark:border-blue-500 dark:ring-blue-900/50",
            isPointerModeEnabled &&
              isSelectingPointerTarget &&
              "border-blue-500 ring-4 ring-blue-400/60"
          )}
          style={boardStyle}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={handleBoardClick}
        >
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-slate-900/5 via-transparent to-white/10 dark:from-slate-950/20 dark:to-slate-900/10" />
          {markerEntries.map((entry) => {
            const pointerTarget = pointerTargets[entry.key] ?? null;
            return (
              <VehicleItemMarker
                key={entry.key}
                entry={entry}
                layoutPosition={markerLayouts.get(entry.key)}
                displayMode={isPointerModeEnabled ? "pointer" : "card"}
                pointerTarget={pointerTarget}
                onRequestPointerTarget={
                  isPointerModeEnabled
                    ? () => handlePointerTargetRequest(entry.key)
                    : undefined
                }
                onClearPointerTarget={
                  isPointerModeEnabled ? () => handlePointerTargetClear(entry.key) : undefined
                }
                isPointerTargetPending={pendingPointerKey === entry.key}
              />
            );
          })}
          {items.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center text-sm font-medium text-slate-600 dark:text-slate-300">
              Glissez un équipement sur la photo pour enregistrer son emplacement.
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/40 dark:text-slate-300">
          <label className="flex items-start gap-3 font-semibold text-slate-700 dark:text-slate-100">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-900"
              checked={isPointerModeEnabled}
              onChange={() => setIsPointerModeEnabled((value) => !value)}
            />
            <span>
              Activer le mode pointeur pour afficher un point précis et une flèche reliant chaque
              matériel à sa vignette.
            </span>
          </label>
          <p className="mt-2 text-[11px] font-normal text-slate-500 dark:text-slate-400">
            Ce mode décale les étiquettes afin de libérer la vue sur la photo tout en conservant un
            repère visuel clair.
          </p>
          {isPointerModeEnabled ? (
            <div className="mt-3 space-y-2 text-[11px] text-slate-500 dark:text-slate-400">
              <p>
                Utilisez le bouton « Définir le point » sur une étiquette puis cliquez sur la photo
                pour relier la flèche à l'endroit exact souhaité. Vous pouvez réinitialiser un point à
                tout moment.
              </p>
              {isSelectingPointerTarget ? (
                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-white/80 px-3 py-2 text-[11px] font-semibold text-blue-800 shadow-sm dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200">
                  <span>Cliquez sur la photo pour positionner le point de référence.</span>
                  <button
                    type="button"
                    className="rounded-full border border-blue-500 px-3 py-1 text-[11px] font-semibold text-blue-600 transition hover:bg-blue-50 dark:border-blue-400 dark:text-blue-200 dark:hover:bg-blue-900/20"
                    onClick={handleCancelPointerSelection}
                  >
                    Annuler
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {isItemsPanelCollapsed
              ? "Cette section est masquée. Cliquez sur « Afficher » pour consulter les équipements associés à cette vue."
              :
                "Faites glisser un matériel depuis la bibliothèque vers la zone ci-dessus pour l'affecter et le positionner. Vous pouvez déplacer les marqueurs existants pour affiner l'emplacement."}
          </p>
          <button
            type="button"
            onClick={() => setIsItemsPanelCollapsed((value) => !value)}
            aria-expanded={!isItemsPanelCollapsed}
            className="self-start rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white sm:self-auto"
          >
            {isItemsPanelCollapsed ? "Afficher" : "Masquer"}
          </button>
        </div>

        {isItemsPanelCollapsed ? null : (
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
        )}
      </div>
    </div>
  );
}

interface VehicleMarkerEntry {
  key: string;
  name: string;
  quantity: number;
  image_url: string | null;
  position_x: number | null;
  position_y: number | null;
  lot_id: number | null;
  lot_name: string | null;
  lotItemIds: number[];
  tooltip: string | null;
  isLot: boolean;
  primaryItemId: number | null;
  category_id: number | null;
  remise_item_id: number | null;
}

interface MarkerLayoutPosition {
  x: number;
  y: number;
}

interface VehicleItemMarkerProps {
  entry: VehicleMarkerEntry;
  layoutPosition?: MarkerLayoutPosition | null;
  displayMode?: "card" | "pointer";
  pointerTarget?: PointerTarget | null;
  onRequestPointerTarget?: (markerKey: string) => void;
  onClearPointerTarget?: (markerKey: string) => void;
  isPointerTargetPending?: boolean;
}

function VehicleItemMarker({
  entry,
  layoutPosition,
  displayMode = "card",
  pointerTarget,
  onRequestPointerTarget,
  onClearPointerTarget,
  isPointerTargetPending
}: VehicleItemMarkerProps) {
  const positionX = clamp(entry.position_x ?? 0.5, 0, 1);
  const positionY = clamp(entry.position_y ?? 0.5, 0, 1);
  const imageUrl = resolveMediaUrl(entry.image_url);
  const hasImage = Boolean(imageUrl);
  const lotLabel = entry.lot_id ? entry.lot_name ?? `Lot #${entry.lot_id}` : null;
  const baseTitle = `${entry.name} (Qté : ${entry.quantity})${lotLabel ? ` - ${lotLabel}` : ""}`;
  const markerTitle = entry.tooltip ? `${baseTitle}\n${entry.tooltip}` : baseTitle;

  const handleDragStart = (event: DragEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    event.dataTransfer.setData(
      "application/json",
      JSON.stringify({
        itemId: entry.primaryItemId ?? undefined,
        categoryId: entry.category_id,
        remiseItemId: entry.remise_item_id,
        lotId: entry.lot_id,
        lotName: entry.lot_name,
        assignedLotItemIds: entry.isLot ? entry.lotItemIds : undefined,
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
        elementWidth: rect.width,
        elementHeight: rect.height
      })
    );
    event.dataTransfer.effectAllowed = "move";
  };

  const markerContent = (
    <div className="flex items-center gap-2">
      {hasImage ? (
        <img
          src={imageUrl ?? undefined}
          alt={`Illustration de ${entry.name}`}
          className="h-10 w-10 rounded-md border border-white/60 object-cover shadow-sm"
        />
      ) : (
        <div className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 bg-slate-100 text-[9px] font-semibold uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
          N/A
        </div>
      )}
      <div className="text-left">
        <span className="block text-xs font-semibold text-slate-700 dark:text-slate-100">
          {entry.name}
        </span>
        <span className="block text-[10px] text-slate-500 dark:text-slate-300">Qté : {entry.quantity}</span>
        {lotLabel ? (
          <span className="mt-0.5 inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-blue-700 dark:bg-blue-900/60 dark:text-blue-200">
            {lotLabel}
          </span>
        ) : null}
      </div>
    </div>
  );

  if (displayMode === "pointer") {
    const cardX = clamp(layoutPosition?.x ?? positionX, 0, 1);
    const cardY = clamp(layoutPosition?.y ?? positionY, 0, 1);
    const anchorX = clamp(pointerTarget?.x ?? positionX, 0, 1);
    const anchorY = clamp(pointerTarget?.y ?? positionY, 0, 1);
    const hasPointerTarget = Boolean(pointerTarget);
    const pointerComesFromLeft = hasPointerTarget ? anchorX < cardX : false;
    const canDefinePointerTarget = Boolean(onRequestPointerTarget);
    const pointerButtonLabel = isPointerTargetPending
      ? "Cliquez sur la photo"
      : pointerTarget
        ? "Modifier le point"
        : "Définir le point";
    const arrowMarkerId = `pointer-arrow-${entry.key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

    const handleDefinePointerTarget = (event: MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      event.preventDefault();
      if (!onRequestPointerTarget) {
        return;
      }
      onRequestPointerTarget(entry.key);
    };

    const handleClearPointerTarget = (event: MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      event.preventDefault();
      if (!onClearPointerTarget) {
        return;
      }
      onClearPointerTarget(entry.key);
    };

    return (
      <>
        {hasPointerTarget ? (
          <>
            <svg
              className="pointer-events-none absolute inset-0 h-full w-full"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden
            >
              <defs>
                <marker
                  id={arrowMarkerId}
                  viewBox="0 0 12 12"
                  refX="6"
                  refY="6"
                  markerWidth="4"
                  markerHeight="4"
                  orient="auto"
                >
                  <path d="M0,0 L12,6 L0,12 Z" fill="rgba(59,130,246,0.85)" />
                </marker>
              </defs>
              <line
                x1={`${cardX * 100}`}
                y1={`${cardY * 100}`}
                x2={`${anchorX * 100}`}
                y2={`${anchorY * 100}`}
                stroke="rgba(255,255,255,0.85)"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
              <line
                x1={`${cardX * 100}`}
                y1={`${cardY * 100}`}
                x2={`${anchorX * 100}`}
                y2={`${anchorY * 100}`}
                stroke="rgba(59,130,246,0.85)"
                strokeWidth="1.5"
                strokeLinecap="round"
                markerEnd={`url(#${arrowMarkerId})`}
              />
            </svg>
            <span
              className="pointer-events-none absolute block -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-blue-500 shadow-lg"
              style={{ left: `${anchorX * 100}%`, top: `${anchorY * 100}%`, width: "10px", height: "10px" }}
            />
          </>
        ) : null}
        <div
          className="group absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${cardX * 100}%`, top: `${cardY * 100}%` }}
        >
          <button
            type="button"
            title={markerTitle}
            draggable
            onDragStart={handleDragStart}
            className="cursor-move rounded-lg bg-white/95 px-3 py-2 text-xs font-medium text-slate-700 shadow-md backdrop-blur-sm transition hover:scale-[1.02] dark:bg-slate-900/85 dark:text-slate-200"
          >
            {markerContent}
          </button>
          <div
            className={clsx(
              "mt-1 flex flex-wrap items-center gap-2 text-[10px] font-semibold",
              pointerComesFromLeft ? "justify-start" : "justify-end"
            )}
          >
            <button
              type="button"
              onClick={handleDefinePointerTarget}
              disabled={!canDefinePointerTarget || Boolean(isPointerTargetPending)}
              className={clsx(
                "rounded-full border px-2 py-0.5",
                isPointerTargetPending
                  ? "border-amber-500 text-amber-600"
                  : "border-blue-400 text-blue-600 hover:bg-blue-50 dark:border-blue-500 dark:text-blue-200"
              )}
            >
              {pointerButtonLabel}
            </button>
            {pointerTarget ? (
              <button
                type="button"
                onClick={handleClearPointerTarget}
                className="rounded-full border border-slate-300 px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100 dark:border-slate-500 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Réinitialiser
              </button>
            ) : null}
          </div>
        </div>
      </>
    );
  }

  const displayX = clamp(layoutPosition?.x ?? positionX, 0, 1);
  const displayY = clamp(layoutPosition?.y ?? positionY, 0, 1);

  return (
    <button
      type="button"
      className="group absolute -translate-x-1/2 -translate-y-1/2 cursor-move rounded-lg bg-white/90 px-3 py-2 text-xs font-medium text-slate-700 shadow-md backdrop-blur-sm transition hover:scale-105 dark:bg-slate-900/80 dark:text-slate-200"
      style={{ left: `${displayX * 100}%`, top: `${displayY * 100}%` }}
      draggable
      onDragStart={handleDragStart}
      title={markerTitle}
    >
      {markerContent}
    </button>
  );
}

interface VehicleItemsPanelProps {
  title: string;
  description: string;
  emptyMessage: string;
  items: VehicleItem[];
  onItemFeedback?: (feedback: Feedback) => void;
  storageKey: string;
}

function VehicleItemsPanel({
  title,
  description,
  emptyMessage,
  items,
  onItemFeedback,
  storageKey
}: VehicleItemsPanelProps) {
  const [isCollapsed, setIsCollapsed] = usePersistentBoolean(storageKey, false);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{description}</p>
        </div>
        <button
          type="button"
          onClick={() => setIsCollapsed((value) => !value)}
          aria-expanded={!isCollapsed}
          className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
        >
          {isCollapsed ? "Afficher" : "Masquer"}
        </button>
      </div>
      {isCollapsed ? (
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
          Panneau masqué. Cliquez sur « Afficher » pour voir le matériel disponible.
        </p>
      ) : (
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
      )}
    </div>
  );
}

interface DroppableLibraryProps {
  items: VehicleItem[];
  lots?: RemiseLotWithItems[];
  isLoadingLots?: boolean;
  isAssigningLot?: boolean;
  vehicleName: string | null;
  onAssignLot?: (lot: RemiseLotWithItems) => void;
  onDropItem: (itemId: number) => void;
  onDropLot?: (lotId: number, categoryId: number) => void;
  onRemoveFromVehicle: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
}

function DroppableLibrary({
  items,
  lots = [],
  isLoadingLots = false,
  isAssigningLot = false,
  vehicleName,
  onAssignLot,
  onDropItem,
  onDropLot,
  onRemoveFromVehicle,
  onItemFeedback
}: DroppableLibraryProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isCollapsed, setIsCollapsed] = usePersistentBoolean(
    "vehicleInventory:library",
    false
  );

  return (
    <div
      className={clsx(
        "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition dark:border-slate-700 dark:bg-slate-900",
        isHovering && !isCollapsed &&
          "border-blue-400 bg-blue-50/60 text-blue-700 dark:border-blue-500 dark:bg-blue-950/50 dark:text-blue-200",
        isCollapsed && "opacity-90"
      )}
      onDragOver={(event) => {
        if (isCollapsed) {
          return;
        }
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setIsHovering(true);
      }}
      onDragLeave={() => setIsHovering(false)}
      onDrop={(event) => {
        if (isCollapsed) {
          return;
        }
        event.preventDefault();
        setIsHovering(false);
        const data = readDraggedItemData(event);
        if (!data) {
          return;
        }
        if (
          typeof data.lotId === "number" &&
          data.categoryId !== null &&
          data.categoryId !== undefined
        ) {
          if (onDropLot) {
            onDropLot(data.lotId, data.categoryId);
          } else {
            onItemFeedback({
              type: "error",
              text: "Impossible de retirer ce lot depuis cette bibliothèque."
            });
          }
          return;
        }
        if (
          typeof data.itemId === "number" &&
          data.categoryId !== null &&
          data.categoryId !== undefined
        ) {
          onDropItem(data.itemId);
          return;
        }
        if (typeof data.lotId === "number") {
          onItemFeedback({
            type: "error",
            text: "Sélectionnez le véhicule concerné avant de retirer un lot."
          });
        }
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Bibliothèque de matériel
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Glissez un élément depuis cette bibliothèque vers une vue pour l'affecter ou vers la
            bibliothèque pour le retirer du véhicule.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsCollapsed((value) => !value)}
          aria-expanded={!isCollapsed}
          className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
        >
          {isCollapsed ? "Afficher" : "Masquer"}
        </button>
      </div>
      {isCollapsed ? (
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
          Bibliothèque masquée. Cliquez sur « Afficher » pour parcourir le matériel disponible.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h4 className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">Lots disponibles</h4>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Ajoutez un lot complet au véhicule pour préparer son contenu en une seule action.
                </p>
              </div>
              {vehicleName ? (
                <p className="text-[11px] text-slate-500 dark:text-slate-400">{vehicleName}</p>
              ) : (
                <p className="text-[11px] text-slate-500 dark:text-slate-400">Aucun véhicule sélectionné</p>
              )}
            </div>
            {isLoadingLots ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Chargement des lots disponibles...
              </p>
            ) : lots.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Aucun lot complet en stock n'est disponible actuellement.
              </p>
            ) : (
              <div className="space-y-2">
                {lots.map((lot) => {
                  const lotTooltip =
                    lot.items.length > 0
                      ? lot.items.map((entry) => `${entry.quantity} × ${entry.remise_name}`).join("\n")
                      : "Ce lot est encore vide.";
                  const lotImageUrl = resolveMediaUrl(lot.image_url);
                  return (
                    <div
                      key={lot.id}
                      title={lotTooltip}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData(
                          "application/json",
                          JSON.stringify({ lotId: lot.id, lotName: lot.name })
                        );
                        event.dataTransfer.effectAllowed = "copyMove";
                      }}
                      className="rounded-lg border border-slate-200 bg-slate-50 p-3 shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-slate-600"
                    >
                      <div className="flex items-start gap-3">
                        <div className="h-16 w-16 overflow-hidden rounded-md border border-slate-200 bg-white dark:border-slate-600 dark:bg-slate-900">
                          {lotImageUrl ? (
                            <img src={lotImageUrl} alt={`Illustration du lot ${lot.name}`} className="h-full w-full object-cover" />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400 dark:text-slate-500">
                              Aucune image
                            </div>
                          )}
                        </div>
                        <div className="flex-1 space-y-1">
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{lot.name}</p>
                              {lot.description ? (
                                <p className="text-[11px] text-slate-500 dark:text-slate-400">{lot.description}</p>
                              ) : null}
                              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                                {lot.item_count} matériel(s) • {lot.total_quantity} pièce(s)
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => onAssignLot?.(lot)}
                              disabled={!onAssignLot || isAssigningLot}
                              className="rounded-full border border-blue-500 px-3 py-1 text-[11px] font-semibold text-blue-600 transition hover:border-blue-600 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-blue-400 dark:text-blue-200 dark:hover:border-blue-300"
                            >
                              {isAssigningLot ? "Ajout en cours..." : "Ajouter au véhicule"}
                            </button>
                          </div>
                          <p className="text-[10px] text-slate-500 dark:text-slate-400">Glissez ce lot vers la vue sélectionnée pour l'affecter.</p>
                        </div>
                      </div>
                      <ul className="mt-2 space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
                        {lot.items.map((item) => (
                          <li key={item.id} className="flex items-center justify-between gap-2">
                            <span className="truncate">{item.remise_name}</span>
                            <span className="text-[10px] text-slate-500 dark:text-slate-400">
                              {item.quantity} prévu(s) • {item.available_quantity} en stock
                            </span>
                          </li>
                        ))}
                      </ul>
                  </div>
                  );
                })}
              </div>
            )}
          </div>

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
              {lots.length > 0
                ? "Aucun article individuel disponible. Ajoutez un lot pour préparer du matériel."
                : "Aucun matériel disponible. Gérez vos articles depuis l'inventaire remises pour les rendre disponibles ici."}
            </p>
          )}
        </div>
      )}
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

  const imageUrl = resolveMediaUrl(item.image_url);
  const hasImage = Boolean(imageUrl);

  const quantityLabel =
    item.category_id === null
      ? `Stock remise : ${item.remise_quantity ?? 0}`
      : `Qté : ${item.quantity}`;
  const isLockedByLot = item.lot_id !== null;
  const lotLabel = isLockedByLot ? item.lot_name ?? `Lot #${item.lot_id}` : null;

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
    if (isLockedByLot) {
      onFeedback?.({
        type: "error",
        text: `Ce matériel appartient au ${lotLabel ?? "lot"}. Retirez-le depuis la gestion des lots.`,
      });
      return;
    }
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
            categoryId: item.category_id,
            remiseItemId: item.remise_item_id,
            lotId: item.lot_id,
            lotName: item.lot_name,
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
          <p className="text-xs text-slate-500 dark:text-slate-400">{quantityLabel}</p>
          {lotLabel ? (
            <p className="mt-1 inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:bg-blue-900/40 dark:text-blue-200">
              {lotLabel}
            </p>
          ) : null}
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
            disabled={isLockedByLot}
            title={
              isLockedByLot
                ? "Ce matériel est verrouillé car il appartient à un lot."
                : undefined
            }
            className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
          >
            Retirer
          </button>
        ) : null}
        {isUpdatingImage ? (
          <span className="text-[11px] text-slate-500 dark:text-slate-400">Enregistrement…</span>
        ) : null}
      </div>
      {isLockedByLot ? (
        <p className="rounded-lg border border-dashed border-blue-200 bg-blue-50 px-3 py-2 text-[11px] text-blue-700 dark:border-blue-900/60 dark:bg-blue-900/30 dark:text-blue-200">
          Ce matériel est verrouillé car il dépend du {lotLabel}. Ajustez son contenu depuis la page des lots.
        </p>
      ) : null}
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

function buildVehicleMarkerEntries(items: VehicleItem[]): VehicleMarkerEntry[] {
  if (items.length === 0) {
    return [];
  }
  const groupedLots = new Map<number, VehicleItem[]>();
  for (const item of items) {
    if (item.lot_id === null) {
      continue;
    }
    const existing = groupedLots.get(item.lot_id) ?? [];
    existing.push(item);
    groupedLots.set(item.lot_id, existing);
  }

  const renderedLots = new Set<number>();
  const markers: VehicleMarkerEntry[] = [];
  for (const item of items) {
    if (item.lot_id === null) {
      markers.push(createMarkerFromItem(item));
      continue;
    }
    if (renderedLots.has(item.lot_id)) {
      continue;
    }
    const group = groupedLots.get(item.lot_id) ?? [];
    markers.push(createMarkerFromLotGroup(item.lot_id, group));
    renderedLots.add(item.lot_id);
  }

  return markers;
}

function buildMarkerLayoutMap(entries: VehicleMarkerEntry[]): Map<string, MarkerLayoutPosition> {
  const layout = new Map<string, MarkerLayoutPosition>();
  if (entries.length === 0) {
    return layout;
  }

  const clusters: {
    base: MarkerLayoutPosition;
    members: { entry: VehicleMarkerEntry; base: MarkerLayoutPosition }[];
  }[] = [];

  const DISTANCE_THRESHOLD = 0.07;

  for (const entry of entries) {
    const base = {
      x: clamp(entry.position_x ?? 0.5, 0, 1),
      y: clamp(entry.position_y ?? 0.5, 0, 1)
    };
    let cluster = clusters.find((candidate) =>
      getMarkerDistance(candidate.base, base) <= DISTANCE_THRESHOLD
    );
    if (!cluster) {
      cluster = { base, members: [] };
      clusters.push(cluster);
    }
    cluster.members.push({ entry, base });
  }

  for (const cluster of clusters) {
    if (cluster.members.length === 1) {
      const [member] = cluster.members;
      layout.set(member.entry.key, member.base);
      continue;
    }
    const distributedPositions = [
      cluster.base,
      ...generateLotPositions(cluster.base, cluster.members.length - 1)
    ];
    cluster.members.forEach((member, index) => {
      const coords = distributedPositions[index] ?? cluster.base;
      layout.set(member.entry.key, coords);
    });
  }

  return layout;
}

function createMarkerFromItem(item: VehicleItem): VehicleMarkerEntry {
  return {
    key: `item-${item.id}`,
    name: item.name,
    quantity: item.quantity,
    image_url: item.image_url,
    position_x: item.position_x,
    position_y: item.position_y,
    lot_id: item.lot_id,
    lot_name: item.lot_name,
    lotItemIds: [item.id],
    tooltip: null,
    isLot: false,
    primaryItemId: item.id,
    category_id: item.category_id,
    remise_item_id: item.remise_item_id
  };
}

function createMarkerFromLotGroup(
  lotId: number,
  lotItems: VehicleItem[]
): VehicleMarkerEntry {
  const [representative] = lotItems;
  const lotName = representative?.lot_name ?? `Lot #${lotId}`;
  const totalQuantity = lotItems.reduce((sum, entry) => sum + entry.quantity, 0);
  const tooltip =
    lotItems.length > 0
      ? lotItems.map((entry) => `${entry.quantity} × ${entry.name}`).join("\n")
      : "Ce lot est encore vide.";
  const { x, y } = computeLotAveragePosition(lotItems);

  return {
    key: `lot-${lotId}`,
    name: lotName,
    quantity: totalQuantity,
    image_url: null,
    position_x: x,
    position_y: y,
    lot_id: lotId,
    lot_name: lotName,
    lotItemIds: lotItems.map((entry) => entry.id),
    tooltip,
    isLot: true,
    primaryItemId: representative?.id ?? null,
    category_id: representative?.category_id ?? null,
    remise_item_id: representative?.remise_item_id ?? null
  };
}

function computeLotAveragePosition(
  lotItems: VehicleItem[]
): { x: number | null; y: number | null } {
  if (lotItems.length === 0) {
    return { x: 0.5, y: 0.5 };
  }
  let sumX = 0;
  let sumY = 0;
  let count = 0;
  for (const entry of lotItems) {
    if (
      typeof entry.position_x === "number" &&
      typeof entry.position_y === "number"
    ) {
      sumX += entry.position_x;
      sumY += entry.position_y;
      count += 1;
    }
  }
  if (count === 0) {
    const [first] = lotItems;
    return {
      x: first?.position_x ?? 0.5,
      y: first?.position_y ?? 0.5
    };
  }
  return { x: sumX / count, y: sumY / count };
}

function readDraggedItemData(event: DragEvent<HTMLElement>): DraggedItemData | null {
  const rawData = event.dataTransfer.getData("application/json");
  if (!rawData) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawData) as Partial<DraggedItemData>;
    const hasItemId = typeof parsed.itemId === "number";
    const hasLotId = typeof parsed.lotId === "number";
    const lotIdIsNull = parsed.lotId === null;
    if (!hasItemId && !hasLotId && !lotIdIsNull) {
      return null;
    }
    return {
      itemId: hasItemId ? parsed.itemId : undefined,
      categoryId:
        typeof parsed.categoryId === "number"
          ? parsed.categoryId
          : parsed.categoryId === null
            ? null
            : undefined,
      remiseItemId:
        typeof parsed.remiseItemId === "number"
          ? parsed.remiseItemId
          : parsed.remiseItemId === null
            ? null
            : undefined,
      lotId: hasLotId ? parsed.lotId : lotIdIsNull ? null : undefined,
      lotName: typeof parsed.lotName === "string" ? parsed.lotName : undefined,
      assignedLotItemIds: Array.isArray(parsed.assignedLotItemIds)
        ? parsed.assignedLotItemIds
            .map((entry) => (typeof entry === "number" ? entry : null))
            .filter((entry): entry is number => entry !== null)
        : undefined,
      offsetX: typeof parsed.offsetX === "number" ? parsed.offsetX : undefined,
      offsetY: typeof parsed.offsetY === "number" ? parsed.offsetY : undefined,
      elementWidth: typeof parsed.elementWidth === "number" ? parsed.elementWidth : undefined,
      elementHeight: typeof parsed.elementHeight === "number" ? parsed.elementHeight : undefined
    };
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

function generateLotPositions(base: { x: number; y: number }, count: number): { x: number; y: number }[] {
  if (count <= 0) {
    return [];
  }
  if (count === 1) {
    return [
      {
        x: clamp(base.x, 0, 1),
        y: clamp(base.y, 0, 1)
      }
    ];
  }

  const radius = Math.min(0.18, 0.04 + count * 0.015);
  return Array.from({ length: count }, (_, index) => {
    const angle = (index / count) * Math.PI * 2;
    return {
      x: clamp(base.x + Math.cos(angle) * radius, 0, 1),
      y: clamp(base.y + Math.sin(angle) * radius, 0, 1)
    };
  });
}

function getMarkerDistance(a: MarkerLayoutPosition, b: MarkerLayoutPosition): number {
  const deltaX = a.x - b.x;
  const deltaY = a.y - b.y;
  return Math.sqrt(deltaX * deltaX + deltaY * deltaY);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

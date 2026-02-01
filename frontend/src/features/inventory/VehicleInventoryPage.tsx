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
import {
  DndContext,
  DragOverlay,
  DragEndEvent,
  DragStartEvent,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors
} from "@dnd-kit/core";

import vanIllustration from "../../assets/vehicles/vehicle-van.svg";
import pickupIllustration from "../../assets/vehicles/vehicle-pickup.svg";
import ambulanceIllustration from "../../assets/vehicles/vehicle-ambulance.svg";
import { CustomFieldsForm } from "../../components/CustomFieldsForm";
import { api } from "../../lib/api";
import { buildCustomFieldDefaults, CustomFieldDefinition } from "../../lib/customFields";
import { resolveMediaUrl } from "../../lib/media";
import { usePersistentBoolean } from "../../hooks/usePersistentBoolean";
import { VehiclePhotosPanel } from "./VehiclePhotosPanel";
import { useModuleTitle } from "../../lib/moduleTitles";
import { useAuth } from "../auth/useAuth";
import { useThrottledHoverState } from "./useThrottledHoverState";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";
import { SubViewCard, type SubviewCardData } from "./SubViewCard";
import { SubviewPinCard, type SubviewPinCardData } from "./SubviewPinCard";

interface VehicleViewConfig {
  name: string;
  background_photo_id: number | null;
  background_url: string | null;
}

interface VehicleSubviewPin {
  id: number;
  vehicle_id: number;
  view_id: string;
  subview_id: string;
  x_pct: number;
  y_pct: number;
}

interface VehicleSubviewPinList {
  vehicle_id: number;
  view_id: string;
  pins: VehicleSubviewPin[];
}

type VehicleType = string;

interface VehicleTypeEntry {
  id: number;
  code: string;
  label: string;
  is_active: boolean;
}

type InventoryItem =
  | {
      kind: "vehicle";
      id: number;
      categoryId: number;
      view: string;
      position: { x: number; y: number };
    }
  | {
      kind: "pharmacy";
      pharmacyItemId: number;
      availableQuantity: number;
    }
  | {
      kind: "remise";
      remiseItemId: number;
      availableQuantity: number;
    };
type InventorySourceType = InventoryItem["kind"];

interface VehicleCategory {
  id: number;
  name: string;
  sizes: string[];
  image_url: string | null;
  vehicle_type: VehicleType | null;
  view_configs?: VehicleViewConfig[] | null;
  extra?: Record<string, unknown>;
}

interface VehicleItem {
  id: number;
  name: string;
  sku: string;
  category_id: number | null;
  size: string | null;
  target_view?: string | null;
  quantity: number;
  remise_item_id: number | null;
  pharmacy_item_id: number | null;
  remise_quantity: number | null;
  pharmacy_quantity: number | null;
  image_url: string | null;
  position_x: number | null;
  position_y: number | null;
  lot_id: number | null;
  lot_name: string | null;
  applied_lot_source?: string | null;
  applied_lot_assignment_id?: number | null;
  show_in_qr: boolean;
  vehicle_type: VehicleType | null;
  available_quantity?: number | null;
  extra?: Record<string, unknown>;
}

interface VehicleLibraryItem {
  id: number;
  name: string;
  sku: string | null;
  category_id: number | null;
  quantity: number;
  expiration_date: string | null;
  image_url: string | null;
  track_low_stock: boolean;
  low_stock_threshold: number;
}

interface RemiseLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  image_url: string | null;
  cover_image_url: string | null;
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
  size: string | null;
  available_quantity: number;
}

interface RemiseLotWithItems extends RemiseLot {
  items: RemiseLotItem[];
}

interface PharmacyLot {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  image_url: string | null;
  cover_image_url: string | null;
  item_count: number;
  total_quantity: number;
}

interface PharmacyLotItem {
  id: number;
  lot_id: number;
  pharmacy_item_id: number;
  quantity: number;
  compartment_name: string | null;
  pharmacy_name: string;
  pharmacy_sku: string;
  available_quantity: number;
}

interface PharmacyLotWithItems extends PharmacyLot {
  items: PharmacyLotItem[];
}

type LibraryLotSource = "remise" | "pharmacy";

interface LibraryLotItem {
  id: number;
  name: string;
  quantity: number;
  available_quantity: number;
  remise_item_id: number | null;
  pharmacy_item_id: number | null;
  sku: string | null;
}

interface LibraryLot {
  id: number;
  name: string;
  description: string | null;
  image_url: string | null;
  cover_image_url: string | null;
  item_count: number;
  total_quantity: number;
  sku?: string | null;
  code?: string | null;
  items: LibraryLotItem[];
  source: LibraryLotSource;
}

export function LibraryLotCardImage({
  lot,
  showCatalogBadge = false
}: {
  lot: Pick<LibraryLot, "name" | "image_url" | "cover_image_url">;
  showCatalogBadge?: boolean;
}) {
  const resolvedImageUrl = resolveMediaUrl(lot.cover_image_url ?? lot.image_url);
  const shouldShowBadge = showCatalogBadge && Boolean(lot.cover_image_url);

  return (
    <div className="relative h-16 w-16 overflow-hidden rounded-md border border-slate-200 bg-white dark:border-slate-600 dark:bg-slate-900">
      {resolvedImageUrl ? (
        <img src={resolvedImageUrl} alt={`Illustration du lot ${lot.name}`} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400 dark:text-slate-500">
          Aucune image
        </div>
      )}
      {shouldShowBadge ? (
        <span
          className="absolute left-1 top-1 rounded bg-slate-900/80 px-1.5 py-0.5 text-[9px] font-semibold text-white"
          title="Image catalogue du lot"
        >
          Catalogue
        </span>
      ) : null}
    </div>
  );
}

interface VehiclePhoto {
  id: number;
  image_url: string;
  uploaded_at: string;
}

interface VehicleAppliedLot {
  id: number;
  vehicle_id: number;
  vehicle_type: VehicleType | null;
  view: string | null;
  source: string;
  pharmacy_lot_id: number | null;
  lot_name: string | null;
  position_x: number | null;
  position_y: number | null;
  created_at: string | null;
}

interface VehicleAppliedLotDeleteResult {
  restored: boolean;
  lot_id: number | null;
  items_removed: number;
  deleted_assignment_id: number;
  deleted_item_ids: number[];
  deleted_items_count: number;
}

interface VehicleFormValues {
  name: string;
  sizes: string[];
  vehicleType: VehicleType;
  extra: Record<string, unknown>;
}

interface UploadVehicleImagePayload {
  categoryId: number;
  file: File;
}

interface UpdateVehiclePayload {
  categoryId: number;
  name: string;
  sizes: string[];
  vehicleType: VehicleType;
  extra: Record<string, unknown>;
}

interface UpdateItemPayload {
  itemId: number;
  categoryId: number | null;
  size?: string | null;
  targetView?: string | null;
  position?: { x: number; y: number } | null;
  quantity?: number;
  successMessage?: string;
  sourceCategoryId?: number | null;
  remiseItemId?: number | null;
  pharmacyItemId?: number | null;
  suppressFeedback?: boolean;
  extra?: Record<string, unknown>;
}

const VEHICLE_ILLUSTRATIONS = [
  vanIllustration,
  pickupIllustration,
  ambulanceIllustration
];

const DEFAULT_VEHICLE_TYPES: Array<{ code: VehicleType; label: string }> = [
  { code: "incendie", label: "Incendie" },
  { code: "secours_a_personne", label: "Secours à personne" }
];

function getAvailableQuantity(item: VehicleItem): number {
  if (item.remise_item_id !== null) {
    return item.remise_quantity ?? item.available_quantity ?? item.quantity ?? 0;
  }
  if (item.pharmacy_item_id !== null) {
    return item.pharmacy_quantity ?? item.available_quantity ?? item.quantity ?? 0;
  }
  return item.quantity ?? 0;
}

// Vehicle placement (target_view) must stay isolated from the packaging "size" value.
// Some legacy records still store the view in the size field; only fallback to that when
// the backend did not expose a dedicated target_view.
function getItemView(item: VehicleItem): string | null {
  if (item.target_view !== undefined) {
    return item.target_view ?? null;
  }
  if (item.category_id !== null) {
    return item.size ?? null;
  }
  return null;
}

const INVENTORY_DEBUG_ENABLED =
  String(
    import.meta.env.VITE_INVENTORY_DEBUG ??
      // Fallback for environments that don't inject the VITE_ prefix.
      import.meta.env.INVENTORY_DEBUG ??
      "false"
  )
    .toLowerCase()
    .trim() === "true";

const VEHICLE_SUBVIEW_CARDS_ENABLED =
  String(
    import.meta.env.VITE_FEATURE_VEHICLE_SUBVIEW_CARDS ??
      import.meta.env.FEATURE_VEHICLE_SUBVIEW_CARDS ??
      "false"
  )
    .toLowerCase()
    .trim() === "true";

export const DEFAULT_VIEW_LABEL = "VUE PRINCIPALE";

type DragKind =
  | "pharmacy_lot"
  | "remise_lot"
  | "library_item"
  | "applied_lot";

type DraggedItemData = {
  kind: DragKind;
  sourceType?: InventorySourceType;
  sourceId?: number;
  vehicleItemId?: number | null;
  categoryId?: number | null;
  remiseItemId?: number | null;
  pharmacyItemId?: number | null;
  quantity?: number;
  assignedLotItemIds?: number[];
  offsetX?: number;
  offsetY?: number;
  elementWidth?: number;
  elementHeight?: number;
  lotId?: number | null;
  lotName?: string | null;
  appliedLotId?: number | null;
};

export function resolveTargetView(selectedView: string | null): string {
  return normalizeViewName(selectedView ?? DEFAULT_VIEW_LABEL);
}

export type DropRequestPayload = {
  sourceType: InventorySourceType;
  sourceId: number;
  vehicleItemId: number | null;
  categoryId: number;
  position: { x: number; y: number };
  quantity: number | null;
  sourceCategoryId: number | null;
  remiseItemId: number | null;
  pharmacyItemId: number | null;
  targetView: string;
  isReposition?: boolean;
  suppressFeedback?: boolean;
};

export function buildDropRequestPayload(params: {
  sourceType: InventorySourceType;
  sourceId: number;
  vehicleItemId?: number | null;
  categoryId: number;
  selectedView: string | null;
  position: { x: number; y: number };
  quantity?: number | null;
  sourceCategoryId?: number | null;
  remiseItemId?: number | null;
  pharmacyItemId?: number | null;
  isReposition?: boolean;
  suppressFeedback?: boolean;
}): DropRequestPayload {
  const targetView = resolveTargetView(params.selectedView);

  const normalizedQuantity =
    params.sourceType === "pharmacy"
      ? Math.max(1, params.quantity ?? 1)
      : params.quantity ?? null;

  return {
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    vehicleItemId: params.vehicleItemId ?? null,
    categoryId: params.categoryId,
    position: params.position,
    quantity: normalizedQuantity,
    sourceCategoryId: params.sourceCategoryId ?? null,
    remiseItemId: params.remiseItemId ?? null,
    pharmacyItemId: params.pharmacyItemId ?? null,
    targetView,
    isReposition: params.isReposition,
    suppressFeedback: params.suppressFeedback
  };
}

function canAssignInventoryItem(payload: DropRequestPayload, vehicleItems: VehicleItem[]): boolean {
  if (payload.sourceType === "vehicle") {
    return (
      typeof payload.vehicleItemId === "number" &&
      vehicleItems.some((item) => item.id === payload.vehicleItemId)
    );
  }

  if (payload.sourceType === "pharmacy" || payload.sourceType === "remise") {
    return (payload.quantity ?? 0) > 0;
  }

  return false;
}

function resolveTemplateForSource(items: VehicleItem[], payload: DropRequestPayload): VehicleItem | null {
  if (payload.sourceType === "vehicle" && payload.vehicleItemId !== null) {
    return items.find((item) => item.id === payload.vehicleItemId) ?? null;
  }

  if (payload.sourceType === "pharmacy") {
    return (
      items.find(
        (item) =>
          item.category_id === null &&
          item.pharmacy_item_id === payload.sourceId &&
          item.remise_item_id === null
      ) ?? null
    );
  }

  if (payload.sourceType === "remise") {
    return (
      items.find(
        (item) =>
          item.category_id === null && item.remise_item_id === payload.sourceId
      ) ?? null
    );
  }

  return null;
}

function writeDraggedItemData(
  event: DragEvent<HTMLElement>,
  payload: DraggedItemData
) {
  const serialized = JSON.stringify(payload);
  event.dataTransfer.setData("application/json", serialized);
  // text/plain is required in some browsers to keep drag payloads readable on drop targets
  event.dataTransfer.setData("text/plain", serialized);
}

type DragPayloadSource = Pick<
  VehicleItem,
  | "id"
  | "category_id"
  | "remise_item_id"
  | "pharmacy_item_id"
  | "lot_id"
  | "lot_name"
  | "quantity"
  | "available_quantity"
>;

type DragSourceDescriptor = {
  sourceType: InventorySourceType;
  sourceId: number;
  vehicleItemId: number | null;
  categoryId: number | null;
  remiseItemId: number | null;
  pharmacyItemId: number | null;
  quantity: number;
};

function resolveDragSource(item: DragPayloadSource): DragSourceDescriptor | null {
  if (item.category_id !== null) {
    return {
      sourceType: "vehicle",
      sourceId: item.id,
      vehicleItemId: item.id,
      categoryId: item.category_id,
      remiseItemId: item.remise_item_id ?? null,
      pharmacyItemId: item.pharmacy_item_id ?? null,
      quantity: item.quantity ?? 0
    };
  }

  if (item.remise_item_id !== null) {
    return {
      sourceType: "remise",
      sourceId: item.remise_item_id,
      vehicleItemId: null,
      categoryId: null,
      remiseItemId: item.remise_item_id,
      pharmacyItemId: null,
      quantity: item.available_quantity ?? item.quantity ?? 0
    };
  }

  if (item.pharmacy_item_id !== null) {
    return {
      sourceType: "pharmacy",
      sourceId: item.pharmacy_item_id,
      vehicleItemId: null,
      categoryId: null,
      remiseItemId: null,
      pharmacyItemId: item.pharmacy_item_id,
      quantity: item.available_quantity ?? item.quantity ?? 0
    };
  }

  return null;
}

function writeItemDragPayload(
  event: DragEvent<HTMLElement>,
  item: DragPayloadSource,
  options?: { assignedLotItemIds?: number[] }
) {
  const source = resolveDragSource(item);
  if (!source) {
    console.error("[vehicle-inventory] Unable to build drag source from item", item);
    event.preventDefault();
    return;
  }
  const rect = event.currentTarget.getBoundingClientRect();
  writeDraggedItemData(event, {
    kind: "library_item",
    sourceType: source.sourceType,
    sourceId: source.sourceId,
    vehicleItemId: source.vehicleItemId,
    categoryId: source.categoryId,
    remiseItemId: source.remiseItemId,
    pharmacyItemId: source.pharmacyItemId,
    quantity: source.quantity,
    lotId: item.lot_id ?? null,
    lotName: item.lot_name ?? null,
    assignedLotItemIds: options?.assignedLotItemIds,
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
    elementWidth: rect.width,
    elementHeight: rect.height
  });
  event.dataTransfer.effectAllowed = "move";
}

function writeAppliedLotDragPayload(event: DragEvent<HTMLElement>, assignmentId: number) {
  const rect = event.currentTarget.getBoundingClientRect();
  writeDraggedItemData(event, {
    kind: "applied_lot",
    appliedLotId: assignmentId,
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
    elementWidth: rect.width,
    elementHeight: rect.height
  });
  event.dataTransfer.effectAllowed = "move";
}

type Feedback = { type: "success" | "error"; text: string };

type PointerTarget = { x: number; y: number };
type PointerTargetMap = Record<string, PointerTarget>;

function buildItemsPanelStorageKey(vehicleId: number | null, viewName: string): string {
  const vehicleIdentifier = vehicleId ? `vehicle-${vehicleId}` : "no-vehicle";
  const viewIdentifier = normalizeViewName(viewName).replace(/\s+/g, "-");
  return `vehicleInventory:itemsPanel:${vehicleIdentifier}:${viewIdentifier}`;
}

function collectPointerTargetsPayload(targetVehicleId: number | null = null): PointerTargetMap {
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
    if (targetVehicleId !== null && !key.includes(`vehicle-${targetVehicleId}:`)) {
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

function collectPointerModePayload(
  targetVehicleId: number | null,
  views: string[]
): Record<string, boolean> {
  if (typeof window === "undefined") {
    return {};
  }
  const modes: Record<string, boolean> = {};
  for (const view of views) {
    const storageKey = `${buildItemsPanelStorageKey(targetVehicleId, view)}:pointer-mode`;
    const stored = window.localStorage.getItem(storageKey);
    if (stored === "true") {
      modes[normalizeViewName(view)] = true;
    } else if (stored === "false") {
      modes[normalizeViewName(view)] = false;
    }
  }
  return modes;
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
  const moduleTitle = useModuleTitle("vehicle_inventory");
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const debugEnabled = useMemo(
    () => user?.role === "admin" || INVENTORY_DEBUG_ENABLED,
    [user?.role]
  );
  const logDebug = useCallback(
    (...args: unknown[]) => {
      if (!debugEnabled) {
        return;
      }
      console.debug("[vehicle-inventory]", ...args);
    },
    [debugEnabled]
  );
  const [selectedView, setSelectedView] = useState<string | null>(null);
  const requestViewChange = useCallback(
    (next: string | null) => {
      setSelectedView(next);
    },
    []
  );
  const resetView = useCallback(() => {
    setSelectedView(null);
  }, []);
  const lockViewSelection = useCallback(() => {}, []);
  const unlockViewSelection = useCallback(() => {}, []);
  const [selectedVehicleId, setSelectedVehicleId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );
  const [isCreatingVehicle, setIsCreatingVehicle] = useState(false);
  const [vehicleName, setVehicleName] = useState("");
  const [vehicleViewsInput, setVehicleViewsInput] = useState("");
  const [vehicleType, setVehicleType] = useState<VehicleType>("incendie");
  const [vehicleExtra, setVehicleExtra] = useState<Record<string, unknown>>({});
  const [vehicleImageFile, setVehicleImageFile] = useState<File | null>(null);
  const vehicleImageInputRef = useRef<HTMLInputElement | null>(null);
  const [isEditingVehicle, setIsEditingVehicle] = useState(false);
  const [editedVehicleName, setEditedVehicleName] = useState("");
  const [editedVehicleViewsInput, setEditedVehicleViewsInput] = useState("");
  const [editedVehicleType, setEditedVehicleType] = useState<VehicleType | null>(null);
  const [editedVehicleExtra, setEditedVehicleExtra] = useState<Record<string, unknown>>({});
  const [editedVehicleImageFile, setEditedVehicleImageFile] = useState<File | null>(null);
  const editedVehicleImageInputRef = useRef<HTMLInputElement | null>(null);
  const [isBackgroundPanelVisible, setIsBackgroundPanelVisible] = useState(true);
  const [isAddingSubView, setIsAddingSubView] = useState(false);
  const [newSubViewName, setNewSubViewName] = useState("");
  const renderCountRef = useRef(0);
  renderCountRef.current += 1;
  if (import.meta.env.DEV) {
    console.debug("[VehicleInventoryPage] render", {
      count: renderCountRef.current,
      selectedVehicleId,
      selectedView
    });
  }
  const selectedHierarchy = useMemo(() => splitViewHierarchy(selectedView), [selectedView]);
  const prefs = useMemo(
    () => ({
      pinnedViewName: normalizeViewName(selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL)
    }),
    [selectedHierarchy.parent]
  );
  const pinnedViewName = prefs?.pinnedViewName ?? null;

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

  const { data: vehicleTypes = [] } = useQuery({
    queryKey: ["admin-vehicle-types"],
    queryFn: async () => {
      const response = await api.get<VehicleTypeEntry[]>("/admin/vehicle-types");
      return response.data;
    },
    enabled: isAdmin
  });

  const { data: vehicleCustomFields = [] } = useQuery({
    queryKey: ["custom-fields", "vehicles"],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: "vehicles" }
      });
      return response.data;
    },
    enabled: isAdmin
  });

  const { data: vehicleItemCustomFields = [] } = useQuery({
    queryKey: ["custom-fields", "vehicle_items"],
    queryFn: async () => {
      const response = await api.get<CustomFieldDefinition[]>("/admin/custom-fields", {
        params: { scope: "vehicle_items" }
      });
      return response.data;
    },
    enabled: isAdmin
  });

  const activeVehicleCustomFields = useMemo(
    () => vehicleCustomFields.filter((definition) => definition.is_active),
    [vehicleCustomFields]
  );
  const activeVehicleItemCustomFields = useMemo(
    () => vehicleItemCustomFields.filter((definition) => definition.is_active),
    [vehicleItemCustomFields]
  );

  const vehicleTypeOptions = useMemo(() => {
    const active = vehicleTypes.filter((entry) => entry.is_active);
    if (active.length > 0) {
      return active.map((entry) => ({ code: entry.code, label: entry.label }));
    }
    return DEFAULT_VEHICLE_TYPES;
  }, [vehicleTypes]);

  const vehicleTypeLabels = useMemo(() => {
    const map = new Map<string, string>();
    DEFAULT_VEHICLE_TYPES.forEach((entry) => map.set(entry.code, entry.label));
    vehicleTypeOptions.forEach((entry) => map.set(entry.code, entry.label));
    return map;
  }, [vehicleTypeOptions]);

  useEffect(() => {
    if (!vehicleTypeOptions.some((entry) => entry.code === vehicleType)) {
      setVehicleType(vehicleTypeOptions[0]?.code ?? "incendie");
    }
  }, [vehicleType, vehicleTypeOptions]);

  useEffect(() => {
    setVehicleExtra((previous) => {
      const nextExtra = buildCustomFieldDefaults(activeVehicleCustomFields, previous);
      const shouldUpdate = !areExtraValuesEqual(previous, nextExtra);
      if (import.meta.env.DEV) {
        console.debug("[VehicleInventoryPage] extra sync effect", {
          activeVehicleCustomFieldsCount: activeVehicleCustomFields.length,
          shouldUpdate,
          nextExtraKeys: Object.keys(nextExtra)
        });
      }
      return shouldUpdate ? nextExtra : previous;
    });
  }, [activeVehicleCustomFields]);

  const selectedVehicle = useMemo(
    () => vehicles.find((vehicle) => vehicle.id === selectedVehicleId) ?? null,
    [vehicles, selectedVehicleId]
  );

  const selectedVehicleType = selectedVehicle?.vehicle_type ?? null;
  const normalizedVehicleViews = useMemo(
    () => getVehicleViews(selectedVehicle),
    [selectedVehicle]
  );
  const pinnedView = useMemo(
    () => resolvePinnedView(normalizedVehicleViews, pinnedViewName),
    [normalizedVehicleViews, pinnedViewName]
  );

  useEffect(() => {
    logDebug("SELECTED VEHICLE TYPE", {
      selectedVehicleId,
      selectedVehicleType
    });
  }, [logDebug, selectedVehicleId, selectedVehicleType]);

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

  const { data: remiseLots = [], isLoading: isLoadingRemiseLots } = useQuery({
    queryKey: ["remise-lots-with-items"],
    queryFn: async () => {
      const response = await api.get<RemiseLotWithItems[]>("/remise-inventory/lots/with-items");
      return response.data;
    }
  });

  const {
    data: pharmacyLots = [],
    isLoading: isLoadingPharmacyLots
  } = useQuery({
    queryKey: ["vehicle-library-lots", selectedVehicleType],
    enabled: selectedVehicleType === "secours_a_personne",
    queryFn: async () => {
      const response = await api.get<PharmacyLotWithItems[]>("/vehicle-inventory/library/lots", {
        params: { vehicle_type: "secours_a_personne", vehicle_id: selectedVehicle?.id }
      });
      return response.data;
    }
  });

  const { data: pharmacyLibraryItems = [] } = useQuery({
    queryKey: ["vehicle-library", selectedVehicleType],
    enabled: !!selectedVehicle?.id && selectedVehicleType === "secours_a_personne",
    queryFn: async () => {
      const response = await api.get<VehicleLibraryItem[]>("/vehicle-inventory/library", {
        params: { vehicle_type: "secours_a_personne" }
      });
      return response.data;
    }
  });

  const isLoadingLots =
    selectedVehicleType === "secours_a_personne"
      ? isLoadingPharmacyLots
      : isLoadingRemiseLots;

  const { data: vehiclePhotos = [] } = useQuery({
    queryKey: ["vehicle-photos"],
    queryFn: async () => {
      const response = await api.get<VehiclePhoto[]>("/vehicle-inventory/photos/");
      return response.data;
    }
  });

  const { data: subviewPins } = useQuery({
    queryKey: ["vehicle-subview-pins", selectedVehicle?.id, pinnedViewName],
    enabled:
      VEHICLE_SUBVIEW_CARDS_ENABLED &&
      Boolean(selectedVehicle?.id && pinnedViewName && pinnedView),
    queryFn: async () => {
      if (!selectedVehicle?.id || !pinnedViewName) {
        return { vehicle_id: 0, view_id: pinnedViewName ?? "", pins: [] };
      }
      const response = await api.get<VehicleSubviewPinList>(
        `/vehicles/${selectedVehicle.id}/views/${encodeURIComponent(pinnedViewName)}/subview-pins`
      );
      return response.data;
    }
  });

  const buildUpdatePayload = ({
    categoryId,
    size,
    targetView,
    position,
    quantity,
    sourceCategoryId,
    remiseItemId,
    pharmacyItemId,
    extra
  }: UpdateItemPayload): Record<string, unknown> => ({
    category_id: categoryId,
    ...(size !== undefined ? { size } : {}),
    ...(targetView !== undefined ? { target_view: targetView ?? null } : {}),
    ...(sourceCategoryId !== undefined
      ? { source_category_id: sourceCategoryId ?? null }
      : {}),
    ...(remiseItemId !== undefined ? { remise_item_id: remiseItemId } : {}),
    ...(pharmacyItemId !== undefined ? { pharmacy_item_id: pharmacyItemId } : {}),
    ...(position
      ? { position_x: position.x, position_y: position.y }
      : position === null
        ? { position_x: null, position_y: null }
        : {}),
    ...(typeof quantity === "number" ? { quantity } : {}),
    ...(extra ? { extra } : {})
  });

  const ensureValidSizeForMutation = (value: string | null | undefined) => {
    if (value === null) {
      throw new Error("Invalid size value for mutation.");
    }
    if (typeof value === "string" && value.trim().length === 0) {
      throw new Error("Invalid size value for mutation.");
    }
  };

  const handleItemMutationSuccess = (
    responseData: unknown,
    variables: UpdateItemPayload,
    overrideMessage?: string
  ) => {
    logDebug("MUTATION SUCCESS", { data: responseData, vars: variables });
    if (variables.suppressFeedback) {
      return;
    }
    const message = overrideMessage ?? variables.successMessage;
    if (message) {
      setFeedback({ type: "success", text: message });
      return;
    }
    const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
    setFeedback({
      type: "success",
      text: vehicleName
        ? `Le matériel a été associé à ${vehicleName}.`
        : "Le matériel a été retiré du véhicule."
    });
  };

  const handleItemMutationError = (error: unknown) => {
    logDebug("MUTATION ERROR", error);
    if (error instanceof Error && error.message.includes("Zero quantity updates")) {
      setFeedback({
        type: "error",
        text: "Impossible d'envoyer une quantité nulle sans suppression explicite."
      });
      return;
    }
    if (isAxiosError(error) && error.response?.data?.detail) {
      setFeedback({ type: "error", text: error.response.data.detail });
      return;
    }
    setFeedback({ type: "error", text: "Impossible d'enregistrer les modifications." });
  };

  const updateVehicleItem = useMutation({
    mutationFn: async ({ itemId, quantity, ...payload }: UpdateItemPayload) => {
      if (quantity === 0) {
        throw new Error("Zero quantity updates must use removeVehicleItem.");
      }
      if (payload.size !== undefined) {
        ensureValidSizeForMutation(payload.size);
      }
      if (payload.targetView !== undefined) {
        ensureValidSizeForMutation(payload.targetView);
      }
      const requestBody = buildUpdatePayload({ itemId, quantity, ...payload });
      await api.put(`/vehicle-inventory/${itemId}`, requestBody);
    },
    onMutate: (vars) => logDebug("UPDATE START", vars),
    onSuccess: (responseData, variables) => handleItemMutationSuccess(responseData, variables),
    onError: (error) => handleItemMutationError(error),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-library"] })
      ]);
    }
  });

  const createSubviewPin = useMutation({
    mutationFn: async ({
      subviewId,
      parentViewId,
      vehicleId,
      xPct,
      yPct
    }: {
      subviewId: string;
      parentViewId: string;
      vehicleId: number;
      xPct: number;
      yPct: number;
    }) => {
      const response = await api.post<VehicleSubviewPin>(
        `/vehicles/${vehicleId}/views/${encodeURIComponent(parentViewId)}/subview-pins`,
        { subview_id: subviewId, x_pct: xPct, y_pct: yPct }
      );
      return response.data;
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.status === 409) {
        setFeedback({ type: "error", text: "Sous-vue déjà épinglée." });
        return;
      }
      setFeedback({ type: "error", text: "Impossible d'épingler cette sous-vue." });
    },
    onSettled: () => {
      if (selectedVehicle?.id && pinnedViewName) {
        queryClient.invalidateQueries({
          queryKey: ["vehicle-subview-pins", selectedVehicle.id, pinnedViewName]
        });
      }
    }
  });

  const updateSubviewPin = useMutation({
    mutationFn: async ({
      pinId,
      parentViewId,
      vehicleId,
      xPct,
      yPct
    }: {
      pinId: number;
      parentViewId: string;
      vehicleId: number;
      xPct: number;
      yPct: number;
    }) => {
      const response = await api.patch<VehicleSubviewPin>(
        `/vehicles/${vehicleId}/views/${encodeURIComponent(parentViewId)}/subview-pins/${pinId}`,
        { x_pct: xPct, y_pct: yPct }
      );
      return response.data;
    },
    onMutate: async ({ pinId, xPct, yPct }) => {
      if (!selectedVehicle?.id || !pinnedViewName) {
        return undefined;
      }
      const queryKey = ["vehicle-subview-pins", selectedVehicle.id, pinnedViewName];
      await queryClient.cancelQueries({ queryKey });
      const previous =
        queryClient.getQueryData<VehicleSubviewPinList>(queryKey) ?? null;
      if (previous) {
        queryClient.setQueryData<VehicleSubviewPinList>(queryKey, {
          ...previous,
          pins: previous.pins.map((pin) =>
            pin.id === pinId ? { ...pin, x_pct: xPct, y_pct: yPct } : pin
          )
        });
      }
      return { previous, queryKey };
    },
    onError: (_error, _variables, context) => {
      if (!context?.queryKey) {
        return;
      }
      if (context.previous) {
        queryClient.setQueryData(context.queryKey, context.previous);
      }
    },
    onSettled: (_data, _error, _variables, context) => {
      if (context?.queryKey) {
        queryClient.invalidateQueries({ queryKey: context.queryKey });
      }
    }
  });

  const deleteSubviewPin = useMutation({
    mutationFn: async ({
      pinId,
      parentViewId,
      vehicleId
    }: {
      pinId: number;
      parentViewId: string;
      vehicleId: number;
    }) => {
      await api.delete(
        `/vehicles/${vehicleId}/views/${encodeURIComponent(parentViewId)}/subview-pins/${pinId}`
      );
    },
    onMutate: async ({ pinId }) => {
      if (!selectedVehicle?.id || !pinnedViewName) {
        return undefined;
      }
      const queryKey = ["vehicle-subview-pins", selectedVehicle.id, pinnedViewName];
      await queryClient.cancelQueries({ queryKey });
      const previous =
        queryClient.getQueryData<VehicleSubviewPinList>(queryKey) ?? null;
      if (previous) {
        queryClient.setQueryData<VehicleSubviewPinList>(queryKey, {
          ...previous,
          pins: previous.pins.filter((pin) => pin.id !== pinId)
        });
      }
      return { previous, queryKey };
    },
    onError: (_error, _variables, context) => {
      if (!context?.queryKey) {
        return;
      }
      if (context.previous) {
        queryClient.setQueryData(context.queryKey, context.previous);
      }
      setFeedback({ type: "error", text: "Impossible de retirer cette sous-vue." });
    },
    onSuccess: () => {
      setFeedback({ type: "success", text: "Sous-vue retirée de la vue principale." });
    },
    onSettled: (_data, _error, _variables, context) => {
      if (context?.queryKey) {
        queryClient.invalidateQueries({ queryKey: context.queryKey });
      }
    }
  });

  const handleUpdateExtra = useCallback(
    (item: VehicleItem, extra: Record<string, unknown>) => {
      updateVehicleItem.mutate({
        itemId: item.id,
        categoryId: item.category_id,
        extra,
        suppressFeedback: true,
        successMessage: "Champs personnalisés mis à jour."
      });
    },
    [updateVehicleItem]
  );

  const removeVehicleItem = useMutation({
    mutationFn: async ({ itemId }: UpdateItemPayload) => {
      await api.delete(`/vehicle-inventory/${itemId}`);
    },
    onMutate: (vars) => logDebug("REMOVE START", vars),
    onSuccess: async (responseData, variables) => {
      handleItemMutationSuccess(responseData, variables, variables.successMessage);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["remise-inventory"],
          refetchType: "active"
        }),
        queryClient.invalidateQueries({
          queryKey: ["remise-inventory", "lots"],
          refetchType: "active"
        }),
        queryClient.invalidateQueries({
          queryKey: ["remise-lots-with-items"],
          refetchType: "active"
        }),
        queryClient.invalidateQueries({
          queryKey: ["vehicle-items"],
          refetchType: "active"
        }),
        queryClient.invalidateQueries({
          queryKey: ["vehicle-inventory"],
          refetchType: "active"
        })
      ]);
    },
    onError: (error) => handleItemMutationError(error),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-library"] })
      ]);
    }
  });

  const assignItemToVehicle = useMutation({
    mutationFn: async (payload: DropRequestPayload) => {
      ensureValidSizeForMutation(payload.targetView);

      const templateSourceItems =
        payload.sourceType === "pharmacy" && selectedVehicleType === "secours_a_personne"
          ? pharmacyLibraryInventoryItems
          : items;
      const template = resolveTemplateForSource(templateSourceItems, payload);
      if (!template) {
        throw new Error("Matériel introuvable.");
      }
      const sourceQuantity = getAvailableQuantity(template);
      if (template.remise_item_id == null && template.pharmacy_item_id == null) {
        throw new Error("Ce matériel n'est pas lié à un inventaire disponible.");
      }
      if (sourceQuantity <= 0 || (payload.quantity ?? 0) <= 0) {
        throw new Error(
          template.remise_item_id ? "Stock insuffisant en remise." : "Stock insuffisant en pharmacie."
        );
      }
      const vehicle = vehicles.find((entry) => entry.id === payload.categoryId) ?? null;
      const requestedQuantity = payload.quantity ?? 1;

      if (payload.sourceType === "remise") {
        if (template.remise_item_id == null) {
          throw new Error("Ce matériel n'est pas lié à la remise.");
        }
        const response = await api.post<VehicleItem>("/vehicle-inventory/assign-from-remise", {
          remise_item_id: template.remise_item_id,
          category_id: payload.categoryId,
          vehicle_type: vehicle?.vehicle_type ?? template.vehicle_type ?? null,
          target_view: payload.targetView,
          position: payload.position,
          quantity: requestedQuantity
        });
        return response.data;
      }

      const response = await api.post<VehicleItem>("/vehicle-inventory/", {
        name: template.name,
        sku: template.sku,
        category_id: payload.categoryId,
        size: payload.targetView,
        quantity: requestedQuantity,
        position_x: payload.position.x,
        position_y: payload.position.y,
        remise_item_id: template.remise_item_id ?? undefined,
        pharmacy_item_id: template.pharmacy_item_id ?? undefined,
        target_view: payload.targetView,
        vehicle_type: vehicle?.vehicle_type ?? template.vehicle_type ?? null
      });
      return response.data;
    },
    onMutate: (vars) => logDebug("ASSIGN START", vars),
    onSuccess: (responseData, variables) => {
      logDebug("MUTATION SUCCESS", { data: responseData, vars: variables });
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Un exemplaire a été affecté à ${vehicleName}.`
          : "Le matériel a été affecté au véhicule."
      });
    },
    onError: (error, vars) => {
      logDebug("MUTATION ERROR", error);
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-library"] })
      ]);
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
    mutationFn: async ({ name, sizes, vehicleType, extra }: VehicleFormValues) => {
      const response = await api.post<VehicleCategory>("/vehicle-inventory/categories/", {
        name,
        sizes,
        vehicle_type: vehicleType,
        extra
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
      lot: LibraryLot;
      categoryId: number;
      view: string;
      position: { x: number; y: number } | null;
    }) => {
      const normalizedView = normalizeViewName(view);
      if (lot.source === "pharmacy") {
        await api.post("/vehicle-inventory/apply-pharmacy-lot", {
          vehicle_id: categoryId,
          lot_id: lot.id,
          target_view: normalizedView,
          ...(position ? { drop_position: position } : {})
        });
        return { source: "pharmacy" as const };
      }
      const created: VehicleItem[] = [];
      const basePosition = position ?? { x: 0.5, y: 0.5 };
      const distributedPositions = generateLotPositions(basePosition, lot.items.length);
      for (const [index, item] of lot.items.entries()) {
        if (!item.remise_item_id) {
          throw new Error("Lot remise invalide.");
        }
        const coords = distributedPositions[index] ?? null;
        const response = await api.post<VehicleItem>("/vehicle-inventory/", {
          name: item.name,
          sku: item.sku ?? `REM-${item.id}`,
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
      return { source: "remise" as const, created };
    },
    onSuccess: async (data, variables) => {
      logDebug("MUTATION SUCCESS", { data, vars: variables });
      const vehicleName = vehicles.find((vehicle) => vehicle.id === variables.categoryId)?.name;
      const lotName = variables.lot?.name ?? null;
      setFeedback({
        type: "success",
        text: vehicleName
          ? `Le lot${lotName ? ` ${lotName}` : ""} a été ajouté au véhicule ${vehicleName}.`
          : "Le lot a été ajouté au véhicule."
      });
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] }),
        queryClient.invalidateQueries({ queryKey: ["items"] })
      ];
      if (variables.lot.source === "pharmacy") {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: ["vehicle-library", selectedVehicleType] }),
          queryClient.invalidateQueries({ queryKey: ["vehicle-library-lots", selectedVehicleType] }),
          queryClient.invalidateQueries({ queryKey: ["vehicle-applied-lots"] }),
          queryClient.invalidateQueries({ queryKey: ["vehicle-applied-lots-library"] })
        );
      } else {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: ["remise-lots"] }),
          queryClient.invalidateQueries({ queryKey: ["remise-lots-with-items"] })
        );
      }
      await Promise.all(invalidations);
    },
    onError: (error) => {
      logDebug("MUTATION ERROR", error);
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

  const updateAppliedLotPosition = useMutation({
    mutationFn: async ({
      assignmentId,
      position
    }: {
      assignmentId: number;
      position: { x: number; y: number };
    }) => {
      const response = await api.patch<VehicleAppliedLot>(
        `/vehicle-inventory/applied-lots/${assignmentId}`,
        {
          position_x: position.x,
          position_y: position.y
        }
      );
      return response.data;
    },
    onError: (error) => {
      logDebug("APPLIED LOT UPDATE ERROR", error);
      if (isAxiosError(error) && error.response?.data?.detail) {
        setFeedback({ type: "error", text: error.response.data.detail });
        return;
      }
      setFeedback({
        type: "error",
        text: "Impossible de déplacer ce lot."
      });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vehicle-applied-lots"] });
    }
  });

  const removeAppliedLot = useMutation({
    mutationFn: async (assignmentId: number) => {
      const response = await api.delete<VehicleAppliedLotDeleteResult>(
        `/vehicle-inventory/applied-lots/${assignmentId}`
      );
      return response.data;
    },
    onSuccess: async () => {
      setFeedback({
        type: "success",
        text: "Le lot appliqué a été retiré."
      });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["vehicle-applied-lots", selectedVehicle?.id, normalizedSelectedView]
        }),
        queryClient.invalidateQueries({
          queryKey: ["vehicle-applied-lots-library", selectedVehicle?.id]
        }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-library", selectedVehicleType] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-library-lots", selectedVehicleType] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-items"] })
      ]);
    },
    onError: (error) => {
      if (isAxiosError(error) && error.response?.data?.detail) {
        setFeedback({ type: "error", text: error.response.data.detail });
        return;
      }
      setFeedback({
        type: "error",
        text: "Impossible de retirer ce lot appliqué."
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
    mutationFn: async ({ categoryId, name, sizes, vehicleType, extra }: UpdateVehiclePayload) => {
      const response = await api.put<VehicleCategory>(
        `/vehicle-inventory/categories/${categoryId}`,
        {
          name,
          sizes,
          vehicle_type: vehicleType,
          extra
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
      requestViewChange(null);
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
      setEditedVehicleType(null);
      setEditedVehicleExtra({});
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

  type ExportJobStatus = "queued" | "processing" | "done" | "error" | "cancelled";
  type ExportJobProgress = {
    step?: string | null;
    current?: number | null;
    total?: number | null;
    percent?: number | null;
  };
  type ExportJob = {
    jobId: string;
    status: ExportJobStatus;
    filename?: string | null;
    downloadUrl?: string | null;
    error?: string | null;
    progress?: ExportJobProgress | null;
  };

  const exportLockRef = useRef(false);
  const exportPollingRef = useRef<number | null>(null);
  const [exportJobId, setExportJobId] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem("vehicleInventoryPdfExportJobId");
    } catch {
      return null;
    }
  });
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [isExportLocked, setIsExportLocked] = useState(false);

  const stopExportPolling = useCallback(() => {
    if (exportPollingRef.current !== null) {
      window.clearInterval(exportPollingRef.current);
      exportPollingRef.current = null;
    }
  }, []);

  const handleExportJobStatus = useCallback(
    (payload: ExportJob) => {
      setExportJob(payload);
      if (payload.status === "done" || payload.status === "error" || payload.status === "cancelled") {
        stopExportPolling();
      }
    },
    [stopExportPolling]
  );

  const fetchExportJobStatus = useCallback(
    async (jobId: string) => {
      try {
        const statusResponse = await api.get(`/vehicle-inventory/export/pdf/jobs/${jobId}`);
        const status = statusResponse.data?.status as ExportJobStatus | undefined;
        if (!status) {
          throw new Error("État export PDF indisponible.");
        }
        handleExportJobStatus({
          jobId,
          status,
          filename: statusResponse.data?.filename ?? null,
          downloadUrl: statusResponse.data?.download_url ?? null,
          error: statusResponse.data?.error ?? null,
          progress: statusResponse.data?.progress ?? null
        });
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 404) {
          setExportJob(null);
          setExportJobId(null);
          try {
            window.localStorage.removeItem("vehicleInventoryPdfExportJobId");
          } catch {
            // ignore storage errors
          }
          stopExportPolling();
          return;
        }
        if (import.meta.env.DEV) {
          console.warn("[VehicleInventoryPage] export status polling failed", error);
        }
      }
    },
    [handleExportJobStatus, stopExportPolling]
  );

  const startExportPolling = useCallback(
    (jobId: string) => {
      stopExportPolling();
      fetchExportJobStatus(jobId);
      exportPollingRef.current = window.setInterval(() => {
        fetchExportJobStatus(jobId);
      }, 1000);
    },
    [fetchExportJobStatus, stopExportPolling]
  );

  useEffect(() => {
    if (exportJobId) {
      startExportPolling(exportJobId);
    }
    return () => {
      stopExportPolling();
    };
  }, [exportJobId, startExportPolling, stopExportPolling]);

  useEffect(() => {
    const isActive = exportJob?.status === "queued" || exportJob?.status === "processing";
    setIsExportLocked(Boolean(isActive));
  }, [exportJob]);

  const triggerExportJob = useCallback(async () => {
    if (exportLockRef.current || isExportLocked) {
      return;
    }
    exportLockRef.current = true;
    setIsExportLocked(true);
    const pointerTargets = collectPointerTargetsPayload(selectedVehicle?.id ?? null);
    const pointerModeByView = collectPointerModePayload(
      selectedVehicle?.id ?? null,
      normalizedVehicleViews
    );
    const payload: Record<string, unknown> = {
      pointer_targets: pointerTargets,
      pointer_mode_by_view: pointerModeByView
    };

    if (selectedVehicle) {
      payload.category_ids = [selectedVehicle.id];
    }

    try {
      const jobResponse = await api.post("/vehicle-inventory/export/pdf", payload);
      const jobId = jobResponse.data?.job_id as string | undefined;
      const status = jobResponse.data?.status as ExportJobStatus | undefined;
      if (!jobId || !status) {
        throw new Error("Échec démarrage export PDF.");
      }
      setExportJobId(jobId);
      setExportJob({
        jobId,
        status,
        filename: jobResponse.data?.filename ?? null,
        downloadUrl: null,
        error: null,
        progress: null
      });
      try {
        window.localStorage.setItem("vehicleInventoryPdfExportJobId", jobId);
      } catch {
        // ignore storage errors
      }
      startExportPolling(jobId);
    } catch (error) {
      let message = "Une erreur est survenue lors du lancement de l'export PDF.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setIsExportLocked(false);
      setFeedback({ type: "error", text: message });
    } finally {
      exportLockRef.current = false;
    }
  }, [
    isExportLocked,
    normalizedVehicleViews,
    selectedVehicle,
    startExportPolling
  ]);

  const handleExportPdf = useCallback(() => {
    if (import.meta.env.DEV) {
      console.debug("[VehicleInventoryPage] export requested");
    }
    requestAnimationFrame(() => {
      void triggerExportJob();
    });
  }, [triggerExportJob]);

  const handleCancelExport = useCallback(async () => {
    if (!exportJobId) {
      return;
    }
    try {
      await api.post(`/vehicle-inventory/export/pdf/jobs/${exportJobId}/cancel`);
      await fetchExportJobStatus(exportJobId);
    } catch (error) {
      let message = "Impossible d'annuler l'export PDF.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setFeedback({ type: "error", text: message });
    }
  }, [exportJobId, fetchExportJobStatus]);

  const handleDownloadExport = useCallback(async () => {
    if (!exportJobId) {
      return;
    }
    try {
      const pdfResponse = await api.get(`/vehicle-inventory/export/pdf/jobs/${exportJobId}/download`, {
        responseType: "arraybuffer"
      });
      const blob = new Blob([pdfResponse.data as ArrayBuffer], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const now = new Date();
      const timestamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(
        now.getDate()
      ).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
      link.href = url;
      link.download = exportJob?.filename || `inventaire_vehicules_${timestamp}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      setFeedback({ type: "success", text: "L'inventaire des véhicules a été exporté." });
    } catch (error) {
      let message = "Impossible de télécharger le PDF.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setFeedback({ type: "error", text: message });
    }
  }, [exportJob, exportJobId]);

  const exportStatusLabelMap: Record<ExportJobStatus, string> = {
    queued: "En attente",
    processing: "En cours",
    done: "Terminé",
    error: "Erreur",
    cancelled: "Annulé"
  };
  const exportProgressLabel = useMemo(() => {
    if (!exportJob?.progress) {
      return null;
    }
    const percent =
      typeof exportJob.progress.percent === "number"
        ? `${Math.round(exportJob.progress.percent)}%`
        : null;
    const stepLabel = exportJob.progress.step
      ? exportJob.progress.step.replace(/_/g, " ")
      : null;
    if (percent && stepLabel) {
      return `${stepLabel} · ${percent}`;
    }
    if (percent) {
      return percent;
    }
    if (stepLabel) {
      return stepLabel;
    }
    return null;
  }, [exportJob?.progress]);

  const selectedVehicleFallback = useMemo(() => {
    if (!selectedVehicle) {
      return undefined;
    }
    return vehicleFallbackMap.get(selectedVehicle.id);
  }, [selectedVehicle, vehicleFallbackMap]);

  useEffect(() => {
    if (selectedVehicleId === null) {
      setIsEditingVehicle(false);
      setEditedVehicleName("");
      setEditedVehicleViewsInput("");
      setEditedVehicleType(null);
      resetView();
    }
  }, [resetView, selectedVehicleId]);

  useEffect(() => {
    setIsAddingSubView(false);
    setNewSubViewName("");
  }, [selectedVehicleId]);

  useEffect(() => {
    const handleDragSessionEnd = () => {
      unlockViewSelection();
    };

    window.addEventListener("dragend", handleDragSessionEnd);
    window.addEventListener("drop", handleDragSessionEnd);

    return () => {
      window.removeEventListener("dragend", handleDragSessionEnd);
      window.removeEventListener("drop", handleDragSessionEnd);
    };
  }, [unlockViewSelection]);

  const normalizedSelectedView = useMemo(
    () => normalizeViewName(selectedView ?? DEFAULT_VIEW_LABEL),
    [selectedView]
  );

  const { data: appliedLots = [] } = useQuery({
    queryKey: ["vehicle-applied-lots", selectedVehicle?.id, normalizedSelectedView],
    enabled: !!selectedVehicle?.id,
    queryFn: async () => {
      const response = await api.get<VehicleAppliedLot[]>("/vehicle-inventory/applied-lots", {
        params: {
          vehicle_id: selectedVehicle?.id,
          view: normalizedSelectedView
        }
      });
      return response.data;
    }
  });

  const { data: appliedLotsForLibrary = [] } = useQuery({
    queryKey: ["vehicle-applied-lots-library", selectedVehicle?.id],
    enabled: !!selectedVehicle?.id && selectedVehicleType === "secours_a_personne",
    queryFn: async () => {
      const response = await api.get<VehicleAppliedLot[]>("/vehicle-inventory/applied-lots", {
        params: {
          vehicle_id: selectedVehicle?.id
        }
      });
      return response.data;
    }
  });

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

  const createSubviewForSelectedView = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!selectedVehicle) {
      pushFeedback({ type: "error", text: "Sélectionnez d'abord un véhicule." });
      return;
    }

    const parentView = normalizeViewName(selectedView ?? DEFAULT_VIEW_LABEL);
    const trimmedSubView = newSubViewName.trim();
    if (!trimmedSubView) {
      pushFeedback({ type: "error", text: "Le nom de la sous-vue est obligatoire." });
      return;
    }

    const normalizedSubView = normalizeViewName(trimmedSubView);
    const composedName = `${parentView} - ${normalizedSubView}`;

    const currentViews = selectedVehicle.view_configs?.length
      ? selectedVehicle.view_configs.map((entry) => normalizeViewName(entry.name))
      : selectedVehicle.sizes.map((entry) => normalizeViewName(entry));

    if (currentViews.some((view) => view === composedName)) {
      pushFeedback({ type: "error", text: "Cette sous-vue existe déjà pour ce véhicule." });
      return;
    }

    const updatedViews = Array.from(new Set([...currentViews, composedName]));

    updateVehicle.mutate(
      {
        categoryId: selectedVehicle.id,
        name: selectedVehicle.name,
        sizes: updatedViews,
        vehicleType: selectedVehicle.vehicle_type ?? "incendie",
        extra: selectedVehicle.extra ?? {}
      },
      {
        onSuccess: () => {
          setNewSubViewName("");
          setIsAddingSubView(false);
          requestViewChange(composedName);
          pushFeedback({ type: "success", text: "Sous-vue ajoutée." });
        }
      }
    );
  };

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
      requestViewChange(null);
      return;
    }

    if (selectedView && normalizedVehicleViews.includes(selectedView)) {
      return;
    }

    requestViewChange(normalizedVehicleViews[0] ?? DEFAULT_VIEW_LABEL);
  }, [normalizedVehicleViews, requestViewChange, selectedVehicle, selectedView]);

  const vehicleItems = useMemo(
    () => items.filter((item) => item.category_id === selectedVehicle?.id),
    [items, selectedVehicle?.id]
  );

  const appliedLotItemsByAssignment = useMemo(() => {
    const map = new Map<number, VehicleItem[]>();
    items.forEach((item) => {
      if (!item.applied_lot_assignment_id) {
        return;
      }
      const current = map.get(item.applied_lot_assignment_id) ?? [];
      current.push(item);
      map.set(item.applied_lot_assignment_id, current);
    });
    return map;
  }, [items]);

  const visibleVehicleItems = useMemo(
    () => vehicleItems.filter((item) => !item.applied_lot_assignment_id),
    [vehicleItems]
  );

  useEffect(() => {
    logDebug("RELOADED VEHICLE ITEMS", vehicleItems);
  }, [logDebug, vehicleItems]);

  const viewItemCountMap = useMemo(() => {
    const map = new Map<string, number>();
    visibleVehicleItems.forEach((item) => {
      const view = getItemView(item);
      if (!view) {
        return;
      }
      const normalized = normalizeViewName(view);
      map.set(normalized, (map.get(normalized) ?? 0) + 1);
    });
    return map;
  }, [visibleVehicleItems]);

  const vehicleItemCountMap = useMemo(() => {
    const map = new Map<number, number>();
    items.forEach((item) => {
      if (item.category_id === null) {
        return;
      }
      const current = map.get(item.category_id) ?? 0;
      map.set(item.category_id, current + item.quantity);
    });
    return map;
  }, [items]);

  const itemsForSelectedView = useMemo(
    () =>
      visibleVehicleItems.filter((item) => {
        if (!normalizedSelectedView) {
          return false;
        }
        return normalizeViewName(getItemView(item)) === normalizedSelectedView;
      }),
    [visibleVehicleItems, normalizedSelectedView]
  );

  const itemsWaitingAssignment = useMemo(
    () => visibleVehicleItems.filter((item) => !getItemView(item)),
    [visibleVehicleItems]
  );

  const itemsInOtherViews = useMemo(
    () =>
      visibleVehicleItems.filter((item) => {
        const itemView = getItemView(item);
        if (!itemView) {
          return false;
        }
        if (!normalizedSelectedView) {
          return false;
        }
        return normalizeViewName(itemView) !== normalizedSelectedView;
      }),
    [visibleVehicleItems, normalizedSelectedView]
  );

  const availableSubViews = useMemo(() => {
    if (!pinnedViewName || !pinnedView) {
      return [];
    }
    const parentView = selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL;
    return normalizedVehicleViews.filter((view) => {
      const { parent, subView } = splitViewHierarchy(view);
      if (!subView) {
        return false;
      }
      return normalizeViewName(parent) === normalizeViewName(parentView);
    });
  }, [normalizedVehicleViews, pinnedView, pinnedViewName, selectedHierarchy.parent]);

  const pinnedSubviewIds = useMemo(() => {
    if (!pinnedViewName || !pinnedView) {
      return [];
    }
    return filterPinnedSubviews({
      pinned: (subviewPins?.pins ?? []).map((pin) => pin.subview_id),
      availableSubViews,
      parentView: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL
    });
  }, [
    availableSubViews,
    pinnedView,
    pinnedViewName,
    selectedHierarchy.parent,
    subviewPins?.pins
  ]);

  const subviewCards = useMemo<SubviewCardData[]>(() => {
    if (availableSubViews.length === 0) {
      return [];
    }
    return availableSubViews.map((subView) => ({
      id: subView,
      label: formatSubViewLabel(subView, selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL),
      itemCount: viewItemCountMap.get(normalizeViewName(subView))
    }));
  }, [
    availableSubViews,
    selectedHierarchy.parent,
    viewItemCountMap
  ]);

  const availableSubviewCards = useMemo(
    () =>
      subviewCards.filter(
        (subview) => !pinnedSubviewIds.includes(normalizeViewName(subview.id))
      ),
    [pinnedSubviewIds, subviewCards]
  );

  const [activeSubviewId, setActiveSubviewId] = useState<string | null>(null);

  const activeSubviewCard = useMemo(() => {
    if (!activeSubviewId) {
      return null;
    }
    return subviewCards.find((subview) => subview.id === activeSubviewId) ?? null;
  }, [activeSubviewId, subviewCards]);

  const subviewPinCards = useMemo<SubviewPinCardData[]>(
    () =>
      (subviewPins?.pins ?? [])
        .filter((pin) =>
          pinnedSubviewIds.includes(normalizeViewName(pin.subview_id))
        )
        .map((pin) => ({
          id: pin.id,
          subviewId: pin.subview_id,
          label: formatSubViewLabel(pin.subview_id, selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL),
          itemCount: viewItemCountMap.get(normalizeViewName(pin.subview_id)),
          xPct: pin.x_pct,
          yPct: pin.y_pct
        })),
    [pinnedSubviewIds, selectedHierarchy.parent, subviewPins?.pins, viewItemCountMap]
  );

  useEffect(() => {
    console.log("[SubViewsUI] render", {
      vehicleId: selectedVehicle?.id ?? null,
      viewId: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL,
      subviewsCount: availableSubViews.length
    });
  }, [availableSubViews.length, selectedHierarchy.parent, selectedVehicle?.id]);

  useEffect(() => {
    console.log("[SubViewsUI] pinned", pinnedSubviewIds);
  }, [pinnedSubviewIds]);

  const handleRemoveSubviewPin = useCallback(
    (pinId: number) => {
      if (!selectedVehicle?.id || !pinnedViewName) {
        return;
      }
      deleteSubviewPin.mutate({
        pinId,
        parentViewId: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL,
        vehicleId: selectedVehicle.id
      });
    },
    [deleteSubviewPin, pinnedViewName, selectedHierarchy.parent, selectedVehicle?.id]
  );

  const handleOpenSubview = useCallback(
    (subviewId: string) => {
      requestViewChange(subviewId);
    },
    [requestViewChange]
  );

  const handleSubviewPinCreate = useCallback(
    (subviewId: string, position: { x: number; y: number }) => {
      if (!selectedVehicle?.id || !pinnedViewName || !pinnedView) {
        return;
      }
      const normalized = normalizeViewName(subviewId);
      if (pinnedSubviewIds.some((entry) => normalizeViewName(entry) === normalized)) {
        setFeedback({ type: "error", text: "Sous-vue déjà épinglée." });
        return;
      }
      createSubviewPin.mutate({
        subviewId,
        parentViewId: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL,
        vehicleId: selectedVehicle.id,
        xPct: position.x,
        yPct: position.y
      });
    },
    [
      createSubviewPin,
      pinnedSubviewIds,
      pinnedView,
      pinnedViewName,
      selectedHierarchy.parent,
      selectedVehicle?.id
    ]
  );

  const handleSubviewPinMove = useCallback(
    (pinId: number, position: { x: number; y: number }) => {
      if (!selectedVehicle?.id || !pinnedViewName) {
        return;
      }
      updateSubviewPin.mutate({
        pinId,
        parentViewId: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL,
        vehicleId: selectedVehicle.id,
        xPct: position.x,
        yPct: position.y
      });
    },
    [pinnedViewName, selectedHierarchy.parent, selectedVehicle?.id, updateSubviewPin]
  );

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 }
    })
  );

  const handleSubviewDragStart = useCallback((event: DragStartEvent) => {
    const data = event.active.data.current;
    if (data?.kind === "SUBVIEW" && typeof data.subviewId === "string") {
      setActiveSubviewId(data.subviewId);
      return;
    }
    setActiveSubviewId(null);
  }, []);

  const handleSubviewDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      const data = active.data.current;
      if (typeof over?.id === "string" && over.id.startsWith("SUBVIEW_BOARD:")) {
        const overRect = over.rect;
        if (overRect) {
          if (data?.kind === "SUBVIEW" && typeof data.subviewId === "string") {
            const activeRect = active.rect.current?.translated ?? active.rect.current?.initial;
            if (activeRect) {
              const centerX = activeRect.left + activeRect.width / 2;
              const centerY = activeRect.top + activeRect.height / 2;
              const position = {
                x: clamp((centerX - overRect.left) / overRect.width, 0, 1),
                y: clamp((centerY - overRect.top) / overRect.height, 0, 1)
              };
              handleSubviewPinCreate(data.subviewId, position);
            }
          } else if (data?.kind === "SUBVIEW_PIN" && typeof data.pinId === "number") {
            const position = {
              x: clamp(data.xPct + event.delta.x / overRect.width, 0, 1),
              y: clamp(data.yPct + event.delta.y / overRect.height, 0, 1)
            };
            handleSubviewPinMove(data.pinId, position);
          }
        }
      }
      setActiveSubviewId(null);
    },
    [handleSubviewPinCreate, handleSubviewPinMove]
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

  const remiseItemTypeMap = useMemo(() => {
    const map = new Map<number, VehicleType | null>();
    items.forEach((item) => {
      if (!item.remise_item_id || !item.vehicle_type) {
        return;
      }
      const previous = map.get(item.remise_item_id);
      if (previous === undefined) {
        map.set(item.remise_item_id, item.vehicle_type);
        return;
      }
      if (previous !== null && previous !== item.vehicle_type) {
        map.set(item.remise_item_id, null);
      }
    });
    return map;
  }, [items]);

  const remiseLibraryLots = useMemo<LibraryLot[]>(
    () =>
      remiseLots.map((lot) => ({
        id: lot.id,
        name: lot.name,
        description: lot.description,
        image_url: lot.image_url,
        cover_image_url: lot.cover_image_url,
        item_count: lot.item_count,
        total_quantity: lot.total_quantity,
        source: "remise",
        items: lot.items.map((item) => ({
          id: item.id,
          name: item.remise_name,
          quantity: item.quantity,
          available_quantity: item.available_quantity,
          remise_item_id: item.remise_item_id,
          pharmacy_item_id: null,
          sku: item.remise_sku
        }))
      })),
    [remiseLots]
  );

  const filteredPharmacyLots = useMemo(() => {
    if (appliedLotsForLibrary.length === 0) {
      return pharmacyLots;
    }
    const appliedLotIds = new Set(
      appliedLotsForLibrary
        .map((lot) => lot.pharmacy_lot_id)
        .filter((lotId): lotId is number => typeof lotId === "number")
    );
    return pharmacyLots.filter((lot) => !appliedLotIds.has(lot.id));
  }, [appliedLotsForLibrary, pharmacyLots]);

  const pharmacyLibraryLots = useMemo<LibraryLot[]>(
    () =>
      filteredPharmacyLots.map((lot) => ({
        id: lot.id,
        name: lot.name,
        description: lot.description,
        image_url: lot.image_url,
        cover_image_url: lot.cover_image_url,
        item_count: lot.item_count,
        total_quantity: lot.total_quantity,
        source: "pharmacy",
        items: lot.items.map((item) => ({
          id: item.id,
          name: item.pharmacy_name,
          quantity: item.quantity,
          available_quantity: item.available_quantity,
          remise_item_id: null,
          pharmacy_item_id: item.pharmacy_item_id,
          sku: item.pharmacy_sku
        }))
      })),
    [filteredPharmacyLots]
  );

  const pharmacyLibraryInventoryItems = useMemo(
    () =>
      pharmacyLibraryItems.map((item) => ({
        id: item.id,
        name: item.name,
        sku: item.sku ?? `PHARM-${item.id}`,
        category_id: null,
        size: null,
        target_view: null,
        quantity: item.quantity,
        remise_item_id: null,
        pharmacy_item_id: item.id,
        remise_quantity: null,
        pharmacy_quantity: item.quantity,
        image_url: item.image_url,
        position_x: null,
        position_y: null,
        lot_id: null,
        lot_name: null,
        show_in_qr: false,
        vehicle_type: "secours_a_personne" as VehicleType,
        available_quantity: item.quantity
      })),
    [pharmacyLibraryItems]
  );

  const librarySourceItems =
    selectedVehicleType === "secours_a_personne" ? pharmacyLibraryInventoryItems : items;

  const isCompatibleWithVehicle = useCallback(
    (itemType: VehicleType | null | undefined) =>
      !selectedVehicleType || !itemType || itemType === selectedVehicleType,
    [selectedVehicleType]
  );

  const availableItems = useMemo(
    () =>
      librarySourceItems.filter((item) => {
        if (item.category_id !== null) {
          return false;
        }
        if (item.lot_id !== null) {
          return false;
        }

        const availableQuantity = getAvailableQuantity(item);
        if (availableQuantity <= 0) {
          return false;
        }

        if (item.remise_item_id && lotRemiseItemIds.has(item.remise_item_id)) {
          return false;
        }

        let templateType =
          item.vehicle_type ??
          (item.remise_item_id ? remiseItemTypeMap.get(item.remise_item_id) ?? null : null);
        if (!isCompatibleWithVehicle(templateType)) {
          return false;
        }

        if (selectedVehicleType === "incendie" && templateType === null) {
          templateType = "incendie";
        }

        if (selectedVehicleType === "incendie") {
          const isFromRemise = item.remise_item_id !== null;
          const isIncendieByType = templateType === "incendie";

          if (!isFromRemise && !isIncendieByType) {
            return false;
          }
        }

        if (selectedVehicleType === "secours_a_personne") {
          if (item.pharmacy_item_id === null && templateType !== "secours_a_personne") {
            return false;
          }
        }
        return true;
      }),
    [
      librarySourceItems,
      lotRemiseItemIds,
      remiseItemTypeMap,
      isCompatibleWithVehicle,
      selectedVehicleType
    ]
  );

  const availableLots = useMemo(() => {
    const isVsav = selectedVehicleType === "secours_a_personne";
    const sourceLots = isVsav ? pharmacyLibraryLots : remiseLibraryLots;
    return sourceLots.filter((lot) => {
      if (lot.items.length === 0) {
        return false;
      }
      if (
        lot.items.some(
          (item) => item.quantity <= 0 || item.available_quantity < item.quantity
        )
      ) {
        return false;
      }
      if (isVsav) {
        return true;
      }
      return lot.items.every((item) => {
        if (!item.remise_item_id) {
          return false;
        }
        return isCompatibleWithVehicle(remiseItemTypeMap.get(item.remise_item_id) ?? null);
      });
    });
  }, [
    pharmacyLibraryLots,
    remiseLibraryLots,
    remiseItemTypeMap,
    isCompatibleWithVehicle,
    selectedVehicleType
  ]);

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

  const returnItemToLibrary = useCallback(
    (itemId: number) => {
      removeVehicleItem.mutate({
        itemId,
        categoryId: null,
        position: null,
        successMessage: "Le matériel a été retiré du véhicule."
      });
    },
    [removeVehicleItem]
  );

  const isLoading =
    isLoadingVehicles ||
    isLoadingItems ||
    updateVehicleItem.isPending ||
    removeVehicleItem.isPending ||
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
        sizes: parsedViews,
        vehicleType,
        extra: vehicleExtra
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
      setVehicleType(vehicleTypeOptions[0]?.code ?? "incendie");
      setVehicleExtra(buildCustomFieldDefaults(activeVehicleCustomFields, {}));
      clearVehicleImageSelection();
      setIsCreatingVehicle(false);
      setSelectedVehicleId(finalVehicle.id);
      requestViewChange(null);
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
      setEditedVehicleType(null);
      setEditedVehicleExtra({});
      return;
    }
    setEditedVehicleName(selectedVehicle.name);
    setEditedVehicleViewsInput(getVehicleViews(selectedVehicle).join(", "));
    setEditedVehicleType(selectedVehicle.vehicle_type ?? "incendie");
    setEditedVehicleExtra(buildCustomFieldDefaults(activeVehicleCustomFields, selectedVehicle.extra ?? {}));
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
    setEditedVehicleType(null);
    setEditedVehicleExtra({});
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
    const targetVehicleType = editedVehicleType ?? selectedVehicle.vehicle_type ?? "incendie";
    try {
      await updateVehicle.mutateAsync({
        categoryId: selectedVehicle.id,
        name: trimmedName,
        sizes: parsedViews,
        vehicleType: targetVehicleType,
        extra: editedVehicleExtra
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
      setEditedVehicleType(null);
      setEditedVehicleExtra({});
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

  const vehicleViews = selectedVehicle?.sizes ?? [];

  const blocks: EditablePageBlock[] = [
    {
      id: "vehicle-header",
      title: "Synthèse",
      required: true,
      permissions: ["vehicle_inventory"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 12 },
        md: { x: 0, y: 0, w: 10, h: 12 },
        sm: { x: 0, y: 0, w: 6, h: 12 },
        xs: { x: 0, y: 0, w: 4, h: 12 }
      },
      render: () => (
        <EditableBlock id="vehicle-header">
          <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="space-y-2">
                <div>
                  <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                    {moduleTitle}
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
                    <AppTextInput
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
                  <AppTextInput
                      id="vehicle-views"
                      type="text"
                      value={vehicleViewsInput}
                      onChange={(event) => setVehicleViewsInput(event.target.value)}
                      placeholder="Vue principale, Coffre gauche, Coffre droit"
                      className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    disabled={createVehicle.isPending}
                  />
                </label>
                <label className="flex-1 space-y-1" htmlFor="vehicle-type">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Type de véhicule
                  </span>
                  <select
                    id="vehicle-type"
                    value={vehicleType}
                    onChange={(event) => setVehicleType(event.target.value as VehicleType)}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    disabled={createVehicle.isPending}
                  >
                    {vehicleTypeOptions.map((entry) => (
                      <option key={entry.code} value={entry.code}>
                        {entry.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {activeVehicleCustomFields.length > 0 ? (
                <div className="rounded-md border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-950">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Champs personnalisés
                  </p>
                  <div className="mt-3">
                    <CustomFieldsForm
                      definitions={activeVehicleCustomFields}
                      values={vehicleExtra}
                      onChange={setVehicleExtra}
                      disabled={createVehicle.isPending}
                    />
                  </div>
                </div>
              ) : null}
                <label className="block space-y-1" htmlFor="vehicle-image">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Photo du véhicule (optionnel)
                  </span>
                  <AppTextInput
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
                onClick={handleExportPdf}
                disabled={isExportLocked}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:text-white"
              >
                {isExportLocked ? "Export en cours…" : "Lancer l’export"}
              </button>
              {exportJob?.status === "done" ? (
                <button
                  type="button"
                  onClick={handleDownloadExport}
                  className="inline-flex items-center gap-2 rounded-full border border-emerald-200 px-4 py-2 text-sm font-medium text-emerald-700 transition hover:border-emerald-300 hover:text-emerald-800 dark:border-emerald-500/40 dark:text-emerald-200 dark:hover:border-emerald-400 dark:hover:text-white"
                >
                  Télécharger le PDF
                </button>
              ) : null}
              {(exportJob?.status === "queued" || exportJob?.status === "processing") && (
                <button
                  type="button"
                  onClick={handleCancelExport}
                  className="inline-flex items-center gap-2 rounded-full border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 transition hover:border-rose-300 hover:text-rose-800 dark:border-rose-500/40 dark:text-rose-200 dark:hover:border-rose-400 dark:hover:text-white"
                >
                  Annuler l’export
                </button>
              )}
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
            {exportJob ? (
              <div className="mt-3 w-full rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">Export PDF :</span>
                  <span>{exportStatusLabelMap[exportJob.status]}</span>
                  {exportProgressLabel ? (
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {exportProgressLabel}
                    </span>
                  ) : null}
                  {exportJob.error ? (
                    <span className="text-xs text-rose-600 dark:text-rose-300">
                      {exportJob.error}
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}
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
      </EditableBlock>
      )
    },
    {
      id: "vehicle-list",
      title: "Véhicules",
      permissions: ["vehicle_inventory"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 12, w: 12, h: 16 },
        md: { x: 0, y: 12, w: 10, h: 16 },
        sm: { x: 0, y: 12, w: 6, h: 16 },
        xs: { x: 0, y: 12, w: 4, h: 16 }
      },
      render: () =>
        !selectedVehicle ? (
          <EditableBlock id="vehicle-list">
            <section className="grid min-w-0 w-full gap-6 lg:grid-cols-3">
              {vehicles.map((vehicle) => (
                <VehicleCard
                  key={vehicle.id}
                  vehicle={vehicle}
                  fallbackIllustration={
                    vehicleFallbackMap.get(vehicle.id) ?? VEHICLE_ILLUSTRATIONS[0]
                  }
                  itemCount={vehicleItemCountMap.get(vehicle.id) ?? 0}
                  onClick={() => setSelectedVehicleId(vehicle.id)}
                  vehicleTypeLabels={vehicleTypeLabels}
                />
              ))}
              {vehicles.length === 0 && !isLoading && (
                <p className="col-span-full rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  Aucun véhicule n'a encore été configuré. Ajoutez des véhicules depuis les paramètres
                  de l'inventaire pour commencer l'organisation du matériel.
                </p>
              )}
            </section>
          </EditableBlock>
        ) : null
    },
    {
      id: "vehicle-detail",
      title: "Organisation véhicule",
      permissions: ["vehicle_inventory"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 28, w: 12, h: 30 },
        md: { x: 0, y: 28, w: 10, h: 30 },
        sm: { x: 0, y: 28, w: 6, h: 30 },
        xs: { x: 0, y: 28, w: 4, h: 30 }
      },
      render: () =>
        selectedVehicle && selectedView ? (
          <EditableBlock id="vehicle-detail">
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
                vehicleTypeLabels={vehicleTypeLabels}
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
                  <AppTextInput
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
                  <AppTextInput
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
                <label className="flex-1 space-y-1" htmlFor="edit-vehicle-type">
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Type de véhicule
                  </span>
                  <select
                    id="edit-vehicle-type"
                    value={editedVehicleType ?? selectedVehicle.vehicle_type ?? "incendie"}
                    onChange={(event) => setEditedVehicleType(event.target.value as VehicleType)}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                    disabled={
                      updateVehicle.isPending ||
                      deleteVehicle.isPending ||
                      uploadVehicleImage.isPending
                    }
                  >
                    {vehicleTypeOptions.map((entry) => (
                      <option key={entry.code} value={entry.code}>
                        {entry.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {activeVehicleCustomFields.length > 0 ? (
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                    Champs personnalisés
                  </p>
                  <div className="mt-3">
                    <CustomFieldsForm
                      definitions={activeVehicleCustomFields}
                      values={editedVehicleExtra}
                      onChange={setEditedVehicleExtra}
                      disabled={updateVehicle.isPending || deleteVehicle.isPending}
                    />
                  </div>
                </div>
              ) : null}
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Séparez les différentes vues par des virgules ou des retours à la ligne. La vue "{DEFAULT_VIEW_LABEL}" sera utilisée par défaut si aucune vue n'est fournie.
              </p>
              <label className="block space-y-1" htmlFor="edit-vehicle-image">
                <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                  Photo du véhicule (optionnel)
                </span>
                <AppTextInput
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

          <DndContext
            sensors={sensors}
            onDragStart={handleSubviewDragStart}
            onDragEnd={handleSubviewDragEnd}
            onDragCancel={() => setActiveSubviewId(null)}
          >
            <VehicleViewSelector
              views={normalizedVehicleViews}
              selectedView={selectedView}
              onSelect={requestViewChange}
            />

            {selectedVehicle ? (
              <div className="mt-4 rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/40">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-200">
                      Sous-vues pour {selectedView ?? DEFAULT_VIEW_LABEL}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Créez des vues détaillées (par exemple des rangements dans la cabine) sans quitter la vue principale.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsAddingSubView((previous) => !previous)}
                    className="inline-flex items-center gap-2 rounded-md border border-indigo-200 px-3 py-2 text-xs font-semibold text-indigo-600 transition hover:border-indigo-300 hover:text-indigo-700 dark:border-indigo-500/40 dark:text-indigo-200 dark:hover:border-indigo-400"
                  >
                    {isAddingSubView ? "Fermer" : "Ajouter une sous-vue"}
                  </button>
                </div>
                <div className="mt-4 space-y-4">
                  <section className="space-y-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Sous-vues disponibles
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Glissez une sous-vue directement sur la photo pour l'afficher dans la vue principale.
                      </p>
                    </div>
                    {!pinnedView ? (
                      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                        Aucune vue épinglable n'est disponible pour le moment.
                      </div>
                    ) : availableSubviewCards.length > 0 ? (
                      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        {availableSubviewCards.map((subview) => (
                          <SubViewCard
                            key={subview.id}
                            subview={subview}
                            mode="draggable"
                            dragData={{
                              kind: "SUBVIEW",
                              subviewId: subview.id,
                              parentViewId: selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL,
                              vehicleId: selectedVehicle.id
                            }}
                            onOpen={handleOpenSubview}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                        Aucune sous-vue disponible pour l'instant.
                      </div>
                    )}
                  </section>
                </div>
                {isAddingSubView ? (
                  <form className="mt-3 space-y-2 sm:flex sm:items-end sm:gap-3" onSubmit={createSubviewForSelectedView}>
                    <label className="flex-1 space-y-1" htmlFor="sub-view-name">
                      <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">
                        Nom de la sous-vue
                      </span>
                      <AppTextInput
                        id="sub-view-name"
                        type="text"
                        value={newSubViewName}
                        onChange={(event) => setNewSubViewName(event.target.value)}
                        placeholder="Rangement conducteur, Casier passager..."
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
                        disabled={updateVehicle.isPending}
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={updateVehicle.isPending}
                      className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {updateVehicle.isPending ? "Ajout..." : "Créer la sous-vue"}
                    </button>
                  </form>
                ) : null}
              </div>
            ) : null}

            <div className="grid min-w-0 gap-6 lg:grid-cols-[2fr,1fr]">
              <div className="min-w-0">
                <VehicleCompartment
                  title={selectedView ?? DEFAULT_VIEW_LABEL}
                  description="Déposez ici le matériel pour l'associer à cette vue du véhicule."
                  items={itemsForSelectedView}
                  allItems={items}
                  appliedLots={appliedLots}
                  appliedLotItemsByAssignment={appliedLotItemsByAssignment}
                  subviewPins={VEHICLE_SUBVIEW_CARDS_ENABLED ? subviewPinCards : undefined}
                  parentViewId={selectedHierarchy.parent ?? DEFAULT_VIEW_LABEL}
                  categoryId={selectedVehicle.id}
                  viewConfig={selectedViewConfig}
                  availablePhotos={vehiclePhotos}
                  selectedView={selectedView}
                  onDragStartCapture={lockViewSelection}
                  onDropItem={(dropRequest) => {
                    const targetView = dropRequest.targetView;

                    logDebug("DROP EVENT", {
                      selectedView: dropRequest.targetView,
                      normalizedSelectedView: dropRequest.targetView,
                      backendView: dropRequest.targetView,
                      vehicleViews: selectedVehicle?.sizes ?? [],
                      itemId: dropRequest.vehicleItemId ?? dropRequest.sourceId,
                      position: dropRequest.position,
                      options: dropRequest
                    });

                    const isInternalReposition =
                      dropRequest.sourceType === "vehicle" &&
                      (dropRequest.sourceCategoryId === undefined ||
                        dropRequest.sourceCategoryId === selectedVehicle.id);

                    if (isInternalReposition) {
                      const vehicleItemId = dropRequest.vehicleItemId ?? dropRequest.sourceId;
                      const existingItem = vehicleItems.find(
                        (entry) => entry.id === vehicleItemId
                      );

                      const resolvedQuantity = dropRequest.quantity ?? existingItem?.quantity;
                      if (resolvedQuantity === 0) {
                        pushFeedback({
                          type: "error",
                          text: "Impossible de déplacer un matériel avec une quantité nulle sans suppression explicite."
                        });
                        return;
                      }

                      updateVehicleItem.mutate({
                        itemId: vehicleItemId,
                        categoryId: selectedVehicle.id,
                        targetView,
                        position: dropRequest.position,
                        // Never send quantity: 0 on DROP: the backend interprets it as a removal.
                        quantity: resolvedQuantity ?? undefined,
                        successMessage: dropRequest.suppressFeedback
                          ? undefined
                          : "Position enregistrée."
                      });
                      return;
                    }

                    if (dropRequest.quantity === 0) {
                      pushFeedback({
                        type: "error",
                        text: "Impossible de déplacer un matériel avec une quantité nulle sans suppression explicite."
                      });
                      return;
                    }

                    if (dropRequest.sourceType === "vehicle") {
                      updateVehicleItem.mutate({
                        itemId: dropRequest.vehicleItemId ?? dropRequest.sourceId,
                        categoryId: dropRequest.categoryId,
                        targetView: dropRequest.targetView,
                        position: dropRequest.position,
                        quantity:
                          dropRequest.quantity === 0
                            ? undefined
                            : dropRequest.quantity ?? undefined,
                        sourceCategoryId: dropRequest.sourceCategoryId,
                        remiseItemId: dropRequest.remiseItemId,
                        pharmacyItemId: dropRequest.pharmacyItemId,
                        successMessage:
                          dropRequest.isReposition && !dropRequest.suppressFeedback
                            ? "Position enregistrée."
                            : undefined
                      });
                      return;
                    }

                    assignItemToVehicle.mutate(dropRequest);
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
                    logDebug("DROP EVENT", {
                      selectedView,
                      normalizedSelectedView,
                      vehicleViews,
                      backendView: null,
                      itemId,
                      position: null,
                      options: undefined
                    });
                    removeVehicleItem.mutate({
                      itemId,
                      categoryId: selectedVehicle.id,
                      position: null,
                      successMessage: "Le matériel a été retiré du véhicule."
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
                  onDropAppliedLot={(assignmentId, position) =>
                    updateAppliedLotPosition.mutate({ assignmentId, position })
                  }
                  onOpenSubview={handleOpenSubview}
                  onRemoveSubviewPin={handleRemoveSubviewPin}
                  onRemoveAppliedLot={removeAppliedLot.mutate}
                  isRemovingAppliedLot={removeAppliedLot.isPending}
                  onUpdateItemQuantity={(itemId, quantity) => {
                    if (!selectedVehicle) {
                      return;
                    }
                    const targetView = normalizedSelectedView ?? DEFAULT_VIEW_LABEL;
                    logDebug("DROP EVENT", {
                      selectedView,
                      normalizedSelectedView,
                      vehicleViews,
                      backendView: targetView,
                      itemId,
                      position: undefined,
                      options: undefined
                    });
                    if (quantity === 0) {
                      removeVehicleItem.mutate({
                        itemId,
                        categoryId: selectedVehicle.id,
                        targetView,
                        position: null,
                        successMessage: "Le matériel a été retiré du véhicule."
                      });
                      return;
                    }
                    updateVehicleItem.mutate({
                      itemId,
                      categoryId: selectedVehicle.id,
                      targetView,
                      quantity,
                      successMessage: "Quantité mise à jour."
                    });
                  }}
                />
              </div>

              <aside className="side-panels min-w-0 space-y-6">
                <VehicleItemsPanel
                  title="Matériel dans les autres vues"
                  description="Faites glisser un équipement vers la vue courante pour le déplacer."
                  emptyMessage="Aucun matériel n'est stocké dans les autres vues pour ce véhicule."
                  items={itemsInOtherViews}
                  onItemFeedback={pushFeedback}
                  storageKey="vehicleInventory:panel:otherViews"
                  onDragStartCapture={lockViewSelection}
                  customFieldDefinitions={activeVehicleItemCustomFields}
                  onUpdateExtra={handleUpdateExtra}
                />

                <VehicleItemsPanel
                  title="Matériel en attente d'affectation"
                  description="Ces éléments sont liés au véhicule mais pas à une vue précise."
                  emptyMessage="Tout le matériel est déjà affecté à une vue."
                  items={itemsWaitingAssignment}
                  onItemFeedback={pushFeedback}
                  storageKey="vehicleInventory:panel:pendingAssignment"
                  onDragStartCapture={lockViewSelection}
                  customFieldDefinitions={activeVehicleItemCustomFields}
                  onUpdateExtra={handleUpdateExtra}
                />

                <DroppableLibrary
                  items={availableItems}
                  lots={availableLots}
                  isLoadingLots={isLoadingLots}
                  isAssigningLot={assignLotToVehicle.isPending}
                  vehicleName={selectedVehicle?.name ?? null}
                  vehicleType={selectedVehicleType}
                  onDragStartCapture={lockViewSelection}
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
                  onDropItem={(itemId) => {
                    logDebug("DROP EVENT", {
                      selectedView,
                      normalizedSelectedView,
                      vehicleViews,
                      backendView: null,
                      itemId,
                      position: null,
                      options: undefined
                    });
                    returnItemToLibrary(itemId);
                  }}
                  onDropLot={
                    selectedVehicleType === "secours_a_personne"
                      ? undefined
                      : (lotId, categoryId) => removeLotFromVehicle.mutate({ lotId, categoryId })
                  }
                  onRemoveFromVehicle={(itemId) => {
                    logDebug("DROP EVENT", {
                      selectedView,
                      normalizedSelectedView,
                      vehicleViews,
                      backendView: null,
                      itemId,
                      position: null,
                      options: undefined
                    });
                    returnItemToLibrary(itemId);
                  }}
                  onItemFeedback={pushFeedback}
                  customFieldDefinitions={activeVehicleItemCustomFields}
                  onUpdateExtra={handleUpdateExtra}
                />
              </aside>
            </div>
            <DragOverlay>
              {activeSubviewCard ? (
                <div
                  className="pointer-events-none"
                  style={{ position: "relative", zIndex: 99999 }}
                >
                  <SubviewDragPreview subview={activeSubviewCard} />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
          <VehiclePhotosPanel />
        </section>
          </EditableBlock>
        ) : null
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:vehicle:inventory"
      blocks={blocks}
      className="space-y-6"
    />
  );
}

interface VehicleCardProps {
  vehicle: VehicleCategory;
  fallbackIllustration: string;
  itemCount: number;
  onClick: () => void;
  vehicleTypeLabels: Map<string, string>;
}

function VehicleCard({
  vehicle,
  fallbackIllustration,
  itemCount,
  onClick,
  vehicleTypeLabels
}: VehicleCardProps) {
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
      className="group flex h-full w-full min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-left shadow-sm transition hover:-translate-y-1 hover:border-slate-300 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600"
    >
      <div className="relative h-44 w-full min-w-0 bg-slate-50 dark:bg-slate-800">
        <img
          src={imageSource}
          alt={`Illustration du véhicule ${vehicle.name}`}
          onError={() => setHasImageError(true)}
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-900/30 via-transparent" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-5">
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
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {itemCount > 0
              ? `${itemCount} matériel${itemCount > 1 ? "s" : ""} affecté${
                  itemCount > 1 ? "s" : ""
                }`
              : "Aucun matériel affecté"}
          </p>
          {vehicle.vehicle_type ? (
            <span className="mt-1 inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {vehicleTypeLabels.get(vehicle.vehicle_type) ?? vehicle.vehicle_type}
            </span>
          ) : null}
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
  vehicleTypeLabels: Map<string, string>;
}

function VehicleHeader({
  vehicle,
  itemsCount,
  fallbackIllustration,
  onEdit,
  onDelete,
  isEditing,
  isUpdating,
  isDeleting,
  vehicleTypeLabels
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
              {vehicle.vehicle_type ? (
                <span className="mt-1 inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  {vehicleTypeLabels.get(vehicle.vehicle_type) ?? vehicle.vehicle_type}
                </span>
              ) : null}
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
  selectedView: string | null;
  onSelect: (view: string) => void;
}

type ViewGroup = {
  parent: string;
  subViews: string[];
};

function VehicleViewSelector({ views, selectedView, onSelect }: VehicleViewSelectorProps) {
  const groupedViews = useMemo<ViewGroup[]>(() => {
    const groups = new Map<string, ViewGroup>();

    views.forEach((view) => {
      const { parent, subView } = splitViewHierarchy(view);

      if (!groups.has(parent)) {
        groups.set(parent, { parent, subViews: [] });
      }

      if (subView) {
        groups.get(parent)?.subViews.push(view);
      }
    });

    return Array.from(groups.values());
  }, [views]);

  const selectedHierarchy = useMemo(() => splitViewHierarchy(selectedView), [selectedView]);
  const [expandedParent, setExpandedParent] = useState<string | null>(
    selectedHierarchy.parent ?? groupedViews[0]?.parent ?? null
  );

  useEffect(() => {
    if (selectedHierarchy.parent && selectedHierarchy.parent !== expandedParent) {
      setExpandedParent(selectedHierarchy.parent);
    }
  }, [expandedParent, selectedHierarchy.parent]);

  useEffect(() => {
    if (expandedParent && groupedViews.some((group) => group.parent === expandedParent)) {
      return;
    }
    setExpandedParent(groupedViews[0]?.parent ?? null);
  }, [expandedParent, groupedViews]);

  const activeGroup = expandedParent
    ? groupedViews.find((group) => group.parent === expandedParent)
    : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3">
        {groupedViews.map((group) => {
          const isSelectedParent =
            selectedHierarchy.parent === group.parent || selectedView === group.parent;

          return (
            <button
              key={group.parent}
              type="button"
              onClick={() => {
                setExpandedParent(group.parent);
                onSelect(group.parent);
              }}
              className={clsx(
                "rounded-full border px-4 py-2 text-sm font-medium transition",
                isSelectedParent
                  ? "border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-400 dark:bg-blue-950/50 dark:text-blue-200"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
              )}
            >
              {group.parent}
            </button>
          );
        })}
      </div>

      {activeGroup && activeGroup.subViews.length > 0 ? (
        <div className="flex flex-wrap gap-2 pl-1">
          {activeGroup.subViews.map((subView) => (
            <button
              key={subView}
              type="button"
              onClick={() => {
                setExpandedParent(activeGroup.parent);
                onSelect(subView);
              }}
              className={clsx(
                "rounded-full border px-3 py-1.5 text-xs font-semibold transition",
                selectedView === subView
                  ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-400 dark:bg-indigo-950/50 dark:text-indigo-100"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-800 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
              )}
            >
              {formatSubViewLabel(subView, activeGroup.parent)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function splitViewHierarchy(view: string | null): { parent: string; subView: string | null } {
  if (!view) {
    return { parent: DEFAULT_VIEW_LABEL, subView: null };
  }

  const [parent, ...rest] = view.split(" - ");
  const cleanedParent = parent.trim() || DEFAULT_VIEW_LABEL;
  const subView = rest.join(" - ").trim();

  return {
    parent: cleanedParent,
    subView: subView.length > 0 ? view : null,
  };
}

function formatSubViewLabel(subView: string, parent: string) {
  const prefix = `${parent} - `;
  if (subView.startsWith(prefix)) {
    return subView.slice(prefix.length);
  }
  return subView;
}

interface VehicleCompartmentProps {
  title: string;
  description: string;
  items: VehicleItem[];
  allItems: VehicleItem[];
  appliedLots?: VehicleAppliedLot[];
  appliedLotItemsByAssignment?: Map<number, VehicleItem[]>;
  subviewPins?: SubviewPinCardData[];
  parentViewId: string;
  categoryId: number;
  viewConfig: VehicleViewConfig | null;
  availablePhotos: VehiclePhoto[];
  selectedView: string | null;
  onDropItem: (payload: DropRequestPayload) => void;
  onRemoveItem: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
  onBackgroundChange: (photoId: number | null) => void;
  isUpdatingBackground: boolean;
  backgroundPanelStorageKey: string;
  itemsPanelStorageKey: string;
  onDropLot?: (lotId: number, position: { x: number; y: number }) => void;
  onDropAppliedLot?: (assignmentId: number, position: { x: number; y: number }) => void;
  onUpdateItemQuantity?: (itemId: number, quantity: number) => void;
  onOpenSubview?: (subviewId: string) => void;
  onRemoveSubviewPin?: (pinId: number) => void;
  onDragStartCapture: () => void;
  onRemoveAppliedLot?: (assignmentId: number) => void;
  isRemovingAppliedLot?: boolean;
}

function VehicleCompartment({
  title,
  description,
  items,
  allItems,
  appliedLots = [],
  appliedLotItemsByAssignment = new Map(),
  subviewPins,
  parentViewId,
  categoryId,
  viewConfig,
  availablePhotos,
  selectedView,
  onDropItem,
  onRemoveItem,
  onItemFeedback,
  onBackgroundChange,
  isUpdatingBackground,
  backgroundPanelStorageKey,
  itemsPanelStorageKey,
  onDropLot,
  onDropAppliedLot,
  onUpdateItemQuantity,
  onOpenSubview,
  onRemoveSubviewPin,
  onDragStartCapture,
  onRemoveAppliedLot,
  isRemovingAppliedLot
}: VehicleCompartmentProps) {
  const hover = useThrottledHoverState();
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
  const [hidePointerActions, setHidePointerActions] = usePersistentBoolean(
    `${itemsPanelStorageKey}:pointer-actions-hidden`,
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
  const { isOver: isSubviewOver, setNodeRef: setSubviewDropRef, active: activeSubview } =
    useDroppable({
      id: `SUBVIEW_BOARD:${parentViewId}`,
      data: { accepts: ["SUBVIEW", "SUBVIEW_PIN"] }
    });
  const queryClient = useQueryClient();
  const markerEntries = useMemo(
    () => buildVehicleMarkerEntries(items, appliedLots, appliedLotItemsByAssignment),
    [items, appliedLots, appliedLotItemsByAssignment]
  );
  const markerLayouts = useMemo(() => buildMarkerLayoutMap(markerEntries), [markerEntries]);

  useEffect(() => {
    if (!isPointerModeEnabled) {
      setPendingPointerKey(null);
    }
  }, [isPointerModeEnabled]);

  const setBoardNodeRef = useCallback(
    (node: HTMLDivElement | null) => {
      boardRef.current = node;
      setSubviewDropRef(node);
    },
    [setSubviewDropRef]
  );

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

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const rect = boardRef.current?.getBoundingClientRect() ?? null;

    hover.handleHover(e.nativeEvent, rect);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!boardRef.current) {
      return;
    }
    const nextTarget = event.relatedTarget as Node | null;
    if (nextTarget && boardRef.current.contains(nextTarget)) {
      return;
    }
    hover.resetHover();
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    hover.resetHover();
    const data = readDraggedItemData(event);
    if (!data) {
      return;
    }
    const targetView = resolveTargetView(selectedView);

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
    if (data.kind === "applied_lot") {
      if (typeof data.appliedLotId === "number") {
        if (onDropAppliedLot) {
          onDropAppliedLot(data.appliedLotId, position);
        } else {
          onItemFeedback({
            type: "error",
            text: "Sélectionnez un véhicule avant de déplacer ce lot."
          });
        }
        return;
      }
      onItemFeedback({
        type: "error",
        text: "Données de lot appliqué incomplètes."
      });
      return;
    }
    if (data.kind === "pharmacy_lot" || data.kind === "remise_lot") {
      if (typeof data.lotId === "number") {
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
      onItemFeedback({
        type: "error",
        text: "Données de lot incomplètes."
      });
      return;
    }
    if (data.assignedLotItemIds && data.assignedLotItemIds.length > 0) {
      data.assignedLotItemIds.forEach((lotItemId, index) => {
        const lotItem = allItems.find((item) => item.id === lotItemId) ?? null;
        const dropRequest: DropRequestPayload = {
          sourceType: "vehicle",
          sourceId: lotItemId,
          vehicleItemId: lotItemId,
          categoryId,
          position,
          quantity: lotItem?.quantity ?? null,
          sourceCategoryId: lotItem?.category_id ?? null,
          remiseItemId: lotItem?.remise_item_id ?? null,
          pharmacyItemId: lotItem?.pharmacy_item_id ?? null,
          targetView,
          isReposition: true,
          suppressFeedback: index > 0
        };

        if (!canAssignInventoryItem(dropRequest, allItems)) {
          console.error("[vehicle-inventory] Invalid lot drop payload", dropRequest);
          onItemFeedback({
            type: "error",
            text: "Impossible de déplacer ce lot : données incohérentes."
          });
          return;
        }

        onDropItem(dropRequest);
      });
      return;
    }
    if (!data.sourceType || typeof data.sourceId !== "number") {
      console.error("[vehicle-inventory] Missing drag source information", data);
      onItemFeedback({
        type: "error",
        text: "Données de glisser-déposer incomplètes."
      });
      return;
    }

    const isReposition = data.sourceType === "vehicle";
    const existingItem =
      isReposition && typeof data.vehicleItemId === "number"
        ? allItems.find((item) => item.id === data.vehicleItemId) ?? null
        : null;

    const baseQuantity =
      data.sourceType === "pharmacy" ? Math.max(1, data.quantity ?? 1) : data.quantity ?? 1;
    const normalizedQuantity = isReposition ? existingItem?.quantity ?? null : baseQuantity;

    const dropRequest: DropRequestPayload = {
      sourceType: data.sourceType,
      sourceId: data.sourceId,
      vehicleItemId: data.vehicleItemId ?? null,
      categoryId,
      position,
      quantity: normalizedQuantity,
      sourceCategoryId: data.categoryId ?? null,
      remiseItemId: data.remiseItemId ?? null,
      pharmacyItemId: data.pharmacyItemId ?? null,
      targetView,
      isReposition
    };

    if (dropRequest.sourceType === "pharmacy") {
      dropRequest.quantity = Math.max(1, dropRequest.quantity ?? 1);
    }

    if (
      dropRequest.sourceType === "remise" &&
      dropRequest.targetView &&
      (!dropRequest.quantity || dropRequest.quantity <= 0)
    ) {
      dropRequest.quantity = 1;
    }

    if (!canAssignInventoryItem(dropRequest, allItems)) {
      console.error("[vehicle-inventory] Guard prevented mutation", dropRequest);
      onItemFeedback({
        type: "error",
        text: "Action impossible : matériel introuvable ou quantité invalide."
      });
      return;
    }

    onDropItem(dropRequest);
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

  const isSubviewDragging = activeSubview?.data.current?.kind === "SUBVIEW";
  const isSubviewDropActive = isSubviewDragging && isSubviewOver;
  const isHovering = hover.hoverRef.current;
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
    <div className="min-w-0">
      <div
        className={clsx(
          "flex h-full min-w-0 flex-col gap-6 rounded-2xl border-2 border-dashed bg-white p-6 text-slate-600 shadow-sm transition dark:bg-slate-900",
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

                <AppTextInput
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
          ref={setBoardNodeRef}
          className={clsx(
            "vehicle-view-photo relative min-h-[320px] w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 transition dark:border-slate-700 dark:bg-slate-800",
            (isHovering || isSubviewDropActive) &&
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
          {isSubviewDropActive ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-full border border-blue-200 bg-white/80 px-4 py-2 text-xs font-semibold text-blue-700 shadow-sm backdrop-blur-sm dark:border-blue-800 dark:bg-blue-950/50 dark:text-blue-200">
                Déposez pour épingler cette sous-vue
              </div>
            </div>
          ) : null}
          {subviewPins?.map((pin) => (
            <SubviewPinCard
              key={pin.id}
              pin={pin}
              onOpen={onOpenSubview}
              onRemove={onRemoveSubviewPin}
            />
          ))}
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
                hidePointerActions={hidePointerActions}
                onDragStartCapture={onDragStartCapture}
                onRemoveAppliedLot={onRemoveAppliedLot}
                isRemovingAppliedLot={isRemovingAppliedLot}
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
            <AppTextInput
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
              <label className="flex items-start gap-2">
                <AppTextInput
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-900"
                  checked={hidePointerActions}
                  onChange={() => setHidePointerActions((value) => !value)}
                />
                <span>
                  Masquer les boutons « Modifier le point » et « Réinitialiser » sur les étiquettes afin
                  de désencombrer l'affichage.
                </span>
              </label>
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
                onDragStartCapture={onDragStartCapture}
                onUpdateQuantity={
                  onUpdateItemQuantity
                    ? (quantity) => onUpdateItemQuantity(item.id, quantity)
                    : undefined
                }
                onUpdatePosition={(position) => {
                  const dropRequest = buildDropRequestPayload({
                    sourceType: "vehicle",
                    sourceId: item.id,
                    vehicleItemId: item.id,
                    categoryId,
                    selectedView,
                    position,
                    quantity: item.quantity,
                    sourceCategoryId: item.category_id ?? null,
                    remiseItemId: item.remise_item_id ?? null,
                    pharmacyItemId: item.pharmacy_item_id ?? null,
                    isReposition: true
                  });
                  onDropItem(dropRequest);
                }}
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

function SubviewDragPreview({ subview }: { subview: SubviewCardData }) {
  const itemCountLabel =
    typeof subview.itemCount === "number"
      ? `${subview.itemCount} équipement${subview.itemCount > 1 ? "s" : ""}`
      : null;

  return (
    <div className="w-64 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-xl dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {subview.label}
          </p>
          {itemCountLabel ? (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{itemCountLabel}</p>
          ) : null}
        </div>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-400 dark:border-slate-600 dark:text-slate-300"
          aria-hidden
        >
          ⠿
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-200">
          Sous-vue
        </span>
      </div>
    </div>
  );
}

interface VehicleMarkerEntry {
  key: string;
  kind: "item" | "lot" | "applied_lot";
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
  pharmacy_item_id: number | null;
  applied_lot_id?: number | null;
  applied_lot_source?: string | null;
  applied_lot_items?: VehicleItem[];
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
  hidePointerActions?: boolean;
  onDragStartCapture?: () => void;
  onRemoveAppliedLot?: (assignmentId: number) => void;
  isRemovingAppliedLot?: boolean;
}

function VehicleItemMarker({
  entry,
  layoutPosition,
  displayMode = "card",
  pointerTarget,
  onRequestPointerTarget,
  onClearPointerTarget,
  isPointerTargetPending,
  hidePointerActions = false,
  onDragStartCapture,
  onRemoveAppliedLot,
  isRemovingAppliedLot = false
}: VehicleItemMarkerProps) {
  const positionX = clamp(entry.position_x ?? 0.5, 0, 1);
  const positionY = clamp(entry.position_y ?? 0.5, 0, 1);
  const imageUrl = resolveMediaUrl(entry.image_url);
  const hasImage = Boolean(imageUrl);
  const isAppliedLot = entry.kind === "applied_lot";
  const [isAppliedLotOpen, setIsAppliedLotOpen] = useState(false);
  const lotLabel =
    entry.kind === "lot" && entry.lot_id ? entry.lot_name ?? `Lot #${entry.lot_id}` : null;
  const appliedLotCount = entry.lotItemIds.length;
  const baseTitle = isAppliedLot
    ? `${entry.name} (${appliedLotCount} élément(s))`
    : `${entry.name} (Qté : ${entry.quantity})${lotLabel ? ` - ${lotLabel}` : ""}`;
  const markerTitle = entry.tooltip ? `${baseTitle}\n${entry.tooltip}` : baseTitle;
  const appliedLotItems = entry.applied_lot_items ?? [];
  const handleToggleAppliedLot = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsAppliedLotOpen((previous) => !previous);
  };
  const handleCloseAppliedLot = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsAppliedLotOpen(false);
  };
  const handleRemoveAppliedLot = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!entry.applied_lot_id || !onRemoveAppliedLot) {
      return;
    }
    onRemoveAppliedLot(entry.applied_lot_id);
    setIsAppliedLotOpen(false);
  };

  const handleDragStart = (event: DragEvent<HTMLElement>) => {
    onDragStartCapture?.();
    if (isAppliedLot && entry.applied_lot_id) {
      writeAppliedLotDragPayload(event, entry.applied_lot_id);
      return;
    }
    if (entry.primaryItemId === null) {
      return;
    }
    writeItemDragPayload(
      event,
      {
        id: entry.primaryItemId,
        category_id: entry.category_id,
        remise_item_id: entry.remise_item_id,
        pharmacy_item_id: entry.pharmacy_item_id,
        lot_id: entry.lot_id,
        lot_name: entry.lot_name,
        quantity: entry.quantity
      },
      {
        assignedLotItemIds: entry.isLot ? entry.lotItemIds : undefined
      }
    );
  };

  const markerContent = isAppliedLot ? (
    <div className="flex items-center gap-2">
      <div className="flex h-10 w-10 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 text-[9px] font-semibold uppercase tracking-wide text-emerald-700 shadow-sm dark:border-emerald-600/40 dark:bg-emerald-900/30 dark:text-emerald-200">
        Lot
      </div>
      <div className="text-left">
        <span className="block text-xs font-semibold text-slate-700 dark:text-slate-100">
          {entry.name}
        </span>
        <span className="block text-[10px] text-slate-500 dark:text-slate-300">
          {appliedLotCount} élément(s) • Qté : {entry.quantity}
        </span>
        <span className="mt-0.5 inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-200">
          Lot appliqué
        </span>
      </div>
    </div>
  ) : (
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
        <span className="block text-[10px] text-slate-500 dark:text-slate-300">
          Qté : {entry.quantity}
        </span>
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
              style={{ left: `${anchorX * 100}%`, top: `${anchorY * 100}%`, width: "0.625rem", height: "0.625rem" }}
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
            {hidePointerActions ? null : (
              <>
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
              </>
            )}
            {isAppliedLot ? (
              <>
                <button
                  type="button"
                  onClick={handleToggleAppliedLot}
                  className="rounded-full border border-emerald-300 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-50 dark:border-emerald-500/70 dark:text-emerald-200 dark:hover:bg-emerald-900/30"
                >
                  Voir contenu
                </button>
                <button
                  type="button"
                  onClick={handleRemoveAppliedLot}
                  disabled={!entry.applied_lot_id || !onRemoveAppliedLot || isRemovingAppliedLot}
                  className={clsx(
                    "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                    isRemovingAppliedLot
                      ? "border-slate-200 text-slate-400"
                      : "border-rose-300 text-rose-600 hover:bg-rose-50 dark:border-rose-500/70 dark:text-rose-200 dark:hover:bg-rose-900/30"
                  )}
                >
                  🗑 Retirer le lot
                </button>
              </>
            ) : null}
          </div>
        </div>
        {isAppliedLot && isAppliedLotOpen ? (
          <div
            className="absolute z-20 w-56 -translate-x-1/2 translate-y-3 rounded-xl border border-slate-200 bg-white p-3 text-[11px] text-slate-600 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            style={{ left: `${cardX * 100}%`, top: `${cardY * 100}%` }}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-xs font-semibold text-slate-900 dark:text-slate-100">Contenu du lot</p>
                <p className="text-[10px] text-slate-500 dark:text-slate-400">{entry.name}</p>
              </div>
              <button
                type="button"
                onClick={handleCloseAppliedLot}
                className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Fermer
              </button>
            </div>
            <ul className="mt-2 space-y-1">
              {appliedLotItems.length > 0 ? (
                appliedLotItems.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-2">
                    <span className="truncate">{item.name}</span>
                    <span className="text-[10px] text-slate-500 dark:text-slate-400">
                      {item.quantity}
                    </span>
                  </li>
                ))
              ) : (
                <li className="text-[10px] text-slate-500 dark:text-slate-400">
                  Aucun matériel enregistré.
                </li>
              )}
            </ul>
          </div>
        ) : null}
      </>
    );
  }

  const displayX = clamp(layoutPosition?.x ?? positionX, 0, 1);
  const displayY = clamp(layoutPosition?.y ?? positionY, 0, 1);

  return (
    <div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: `${displayX * 100}%`, top: `${displayY * 100}%` }}>
      <button
        type="button"
        className="group cursor-move rounded-lg bg-white/90 px-3 py-2 text-xs font-medium text-slate-700 shadow-md backdrop-blur-sm transition hover:scale-105 dark:bg-slate-900/80 dark:text-slate-200"
        draggable
        onDragStart={handleDragStart}
        title={markerTitle}
      >
        {markerContent}
      </button>
      {isAppliedLot ? (
        <div className="mt-1 flex items-center gap-2 text-[10px] font-semibold">
          <button
            type="button"
            onClick={handleToggleAppliedLot}
            className="rounded-full border border-emerald-300 px-2 py-0.5 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-500/70 dark:text-emerald-200 dark:hover:bg-emerald-900/30"
          >
            Voir contenu
          </button>
          <button
            type="button"
            onClick={handleRemoveAppliedLot}
            disabled={!entry.applied_lot_id || !onRemoveAppliedLot || isRemovingAppliedLot}
            className={clsx(
              "rounded-full border px-2 py-0.5",
              isRemovingAppliedLot
                ? "border-slate-200 text-slate-400"
                : "border-rose-300 text-rose-600 hover:bg-rose-50 dark:border-rose-500/70 dark:text-rose-200 dark:hover:bg-rose-900/30"
            )}
          >
            🗑 Retirer le lot
          </button>
        </div>
      ) : null}
      {isAppliedLot && isAppliedLotOpen ? (
        <div className="mt-2 w-56 rounded-xl border border-slate-200 bg-white p-3 text-[11px] text-slate-600 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-slate-900 dark:text-slate-100">Contenu du lot</p>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">{entry.name}</p>
            </div>
            <button
              type="button"
              onClick={handleCloseAppliedLot}
              className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Fermer
            </button>
          </div>
          <ul className="mt-2 space-y-1">
            {appliedLotItems.length > 0 ? (
              appliedLotItems.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{item.name}</span>
                  <span className="text-[10px] text-slate-500 dark:text-slate-400">{item.quantity}</span>
                </li>
              ))
            ) : (
              <li className="text-[10px] text-slate-500 dark:text-slate-400">
                Aucun matériel enregistré.
              </li>
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

interface VehicleItemsPanelProps {
  title: string;
  description: string;
  emptyMessage: string;
  items: VehicleItem[];
  onItemFeedback?: (feedback: Feedback) => void;
  storageKey: string;
  onDragStartCapture?: () => void;
  customFieldDefinitions?: CustomFieldDefinition[];
  onUpdateExtra?: (item: VehicleItem, extra: Record<string, unknown>) => void;
}

function VehicleItemsPanel({
  title,
  description,
  emptyMessage,
  items,
  onItemFeedback,
  storageKey,
  onDragStartCapture,
  customFieldDefinitions = [],
  onUpdateExtra
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
            <ItemCard
              key={item.id}
              item={item}
              onFeedback={onItemFeedback}
              onDragStartCapture={onDragStartCapture}
              customFieldDefinitions={customFieldDefinitions}
              onUpdateExtra={onUpdateExtra ? (extra) => onUpdateExtra(item, extra) : undefined}
            />
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
  lots?: LibraryLot[];
  isLoadingLots?: boolean;
  isAssigningLot?: boolean;
  vehicleName: string | null;
  vehicleType?: VehicleType | null;
  onAssignLot?: (lot: LibraryLot) => void;
  onDropItem: (itemId: number) => void;
  onDropLot?: (lotId: number, categoryId: number) => void;
  onRemoveFromVehicle: (itemId: number) => void;
  onItemFeedback: (feedback: Feedback) => void;
  onDragStartCapture: () => void;
  customFieldDefinitions?: CustomFieldDefinition[];
  onUpdateExtra?: (item: VehicleItem, extra: Record<string, unknown>) => void;
}

function DroppableLibrary({
  items,
  lots = [],
  isLoadingLots = false,
  isAssigningLot = false,
  vehicleName,
  vehicleType,
  onAssignLot,
  onDropItem,
  onDropLot,
  onRemoveFromVehicle,
  onItemFeedback,
  onDragStartCapture,
  customFieldDefinitions = [],
  onUpdateExtra
}: DroppableLibraryProps) {
  const hover = useThrottledHoverState();
  const [libraryQuery, setLibraryQuery] = useState("");
  const [isCollapsed, setIsCollapsed] = usePersistentBoolean(
    "vehicleInventory:library",
    false
  );
  const [areLotsCollapsed, setAreLotsCollapsed] = usePersistentBoolean(
    "vehicleInventory:library:lots",
    false
  );
  const [areItemsCollapsed, setAreItemsCollapsed] = usePersistentBoolean(
    "vehicleInventory:library:items",
    false
  );

  const isHovering = hover.hoverRef.current;
  const normalizeSearchValue = (value?: string | null) =>
    value?.toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu, "") ?? "";
  const matchesLibraryQuery = (
    query: string,
    ...fields: Array<string | null | undefined>
  ) => {
    const normalizedQuery = normalizeSearchValue(query).trim();
    if (!normalizedQuery) {
      return true;
    }
    const terms = normalizedQuery.split(/\s+/).filter(Boolean);
    if (terms.length === 0) {
      return true;
    }
    const haystack = fields.map((field) => normalizeSearchValue(field)).join(" ");
    return terms.every((term) => haystack.includes(term));
  };

  const filteredLots = lots.filter((lot) => {
    const lotItemSkus = lot.items?.map((item) => item.sku).filter(Boolean).join(" ");
    return matchesLibraryQuery(libraryQuery, lot.name, lot.sku, lot.code, lotItemSkus);
  });
  const filteredItems = items.filter((item) =>
    matchesLibraryQuery(libraryQuery, item.name, item.sku)
  );
  const lotCountLabel = `${filteredLots.length} lot${filteredLots.length > 1 ? "s" : ""}`;
  const itemCountLabel = `${filteredItems.length} article${filteredItems.length > 1 ? "s" : ""}`;

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
        hover.handleHover(event.nativeEvent, null);
      }}
      onDragLeave={() => {
        hover.resetHover();
      }}
      onDrop={(event) => {
        if (isCollapsed) {
          return;
        }
        event.preventDefault();
        hover.resetHover();
        const data = readDraggedItemData(event);
        if (!data) {
          return;
        }
        if (data.kind === "pharmacy_lot" || data.kind === "remise_lot") {
          onItemFeedback({
            type: "error",
            text: "Impossible de déposer un lot sur cette bibliothèque."
          });
          return;
        }
        if (data.kind === "applied_lot") {
          onItemFeedback({
            type: "error",
            text: "Impossible de déposer un lot appliqué sur cette bibliothèque."
          });
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
          data.sourceType === "vehicle" &&
          typeof data.vehicleItemId === "number" &&
          data.categoryId !== null &&
          data.categoryId !== undefined
        ) {
          onDropItem(data.vehicleItemId);
          return;
        }
        if (typeof data.lotId === "number") {
          onItemFeedback({
            type: "error",
            text: "Sélectionnez le véhicule concerné avant de retirer un lot."
          });
          return;
        }
        console.error("[vehicle-inventory] Unsupported drop payload on library", data);
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
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <div className="flex flex-1 items-center gap-2">
              <label htmlFor="library-search" className="sr-only">
                Recherche
              </label>
              <div className="relative w-full">
                <input
                  id="library-search"
                  type="text"
                  value={libraryQuery}
                  onChange={(event) => setLibraryQuery(event.target.value)}
                  placeholder="Rechercher (nom ou SKU)…"
                  className="w-full rounded-full border border-slate-200 bg-white px-3 py-2 pr-8 text-xs text-slate-700 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-200 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:placeholder:text-slate-500 dark:focus:border-blue-400 dark:focus:ring-blue-500/30"
                />
                {libraryQuery ? (
                  <button
                    type="button"
                    onClick={() => setLibraryQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[12px] font-semibold text-slate-400 transition hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300"
                    aria-label="Effacer la recherche"
                  >
                    ✕
                  </button>
                ) : null}
              </div>
            </div>
            <span className="shrink-0 text-[11px] font-medium text-slate-500 dark:text-slate-400">
              {lotCountLabel} / {itemCountLabel} affichés
            </span>
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">Lots disponibles</h4>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Ajoutez un lot complet au véhicule pour préparer son contenu en une seule action.
                </p>
              </div>
              <div className="flex items-center gap-2">
                {vehicleName ? (
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">{vehicleName}</p>
                ) : (
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">Aucun véhicule sélectionné</p>
                )}
                <button
                  type="button"
                  onClick={() => setAreLotsCollapsed((value) => !value)}
                  aria-expanded={!areLotsCollapsed}
                  className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
                >
                  {areLotsCollapsed ? "Afficher" : "Masquer"}
                </button>
              </div>
            </div>
            {areLotsCollapsed ? (
              <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                Section lots masquée. Cliquez sur « Afficher » pour parcourir les lots disponibles.
              </p>
            ) : isLoadingLots ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Chargement des lots disponibles...
              </p>
            ) : lots.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Aucun lot complet en stock n'est disponible actuellement.
              </p>
            ) : filteredLots.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                Aucun lot ne correspond à la recherche.
              </p>
            ) : (
              <div
                className="grid grid-cols-1 gap-2 overflow-y-auto pr-1 md:grid-cols-2"
                style={{ maxHeight: "calc(2 * 18rem)" }}
              >
                {filteredLots.map((lot) => {
                  const lotTooltip =
                    lot.items.length > 0
                      ? lot.items.map((entry) => `${entry.quantity} × ${entry.name}`).join("\n")
                      : "Ce lot est encore vide.";
                  return (
                    <div
                      key={lot.id}
                      title={lotTooltip}
                      draggable
      onDragStart={(event) => {
        onDragStartCapture();
        writeDraggedItemData(event, {
          kind: lot.source === "pharmacy" ? "pharmacy_lot" : "remise_lot",
          lotId: lot.id,
          lotName: lot.name
        });
        event.dataTransfer.effectAllowed = "copyMove";
      }}
                      className="rounded-lg border border-slate-200 bg-slate-50 p-3 shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-slate-600"
                    >
                      <div className="flex items-start gap-3">
                        <LibraryLotCardImage lot={lot} showCatalogBadge={import.meta.env.DEV} />
                        <div className="flex-1 space-y-1">
                          <div className="flex items-start gap-2">
                            <div>
                              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{lot.name}</p>
                              {lot.description ? (
                                <p className="text-[11px] text-slate-500 dark:text-slate-400">{lot.description}</p>
                              ) : null}
                              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                                {lot.item_count} matériel(s) • {lot.total_quantity} pièce(s)
                              </p>
                            </div>
                          </div>
                          <p className="text-[10px] text-slate-500 dark:text-slate-400">Glissez ce lot vers la vue sélectionnée pour l'affecter.</p>
                        </div>
                      </div>
                      <ul
                        className="mt-2 space-y-1 overflow-y-auto pr-1 text-[11px] text-slate-600 dark:text-slate-300"
                        style={{ maxHeight: "4.5rem" }}
                      >
                        {lot.items.map((item) => (
                          <li key={item.id} className="flex items-center justify-between gap-2">
                            <span className="truncate">{item.name}</span>
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

          <div className="space-y-3 pt-2">
            <div className="flex flex-wrap items-center justify-between gap-3 text-[11px] text-slate-500 dark:text-slate-400">
              <div className="flex flex-1 items-center gap-3">
                <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" aria-hidden />
                <span className="shrink-0 rounded-full bg-slate-100 px-3 py-1 text-[11px] font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  Matériel individuel
                </span>
                <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" aria-hidden />
              </div>
              <button
                type="button"
                onClick={() => setAreItemsCollapsed((value) => !value)}
                aria-expanded={!areItemsCollapsed}
                className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
              >
                {areItemsCollapsed ? "Afficher" : "Masquer"}
              </button>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Glissez un article à l'unité si vous ne souhaitez pas déplacer un lot complet. Les items déposés ici seront retirés
              du véhicule.
            </p>
          </div>

          {areItemsCollapsed ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              Section matériel individuel masquée. Cliquez sur « Afficher » pour consulter les articles disponibles.
            </p>
          ) : (
            <div
              className="space-y-3 overflow-y-auto pr-1"
              style={{ maxHeight: "calc(8 * 5rem)" }}
            >
              {filteredItems.map((item) => (
                <ItemCard
                  key={item.id}
                  item={item}
                  onRemove={() => onRemoveFromVehicle(item.id)}
                  onFeedback={onItemFeedback}
                  onDragStartCapture={onDragStartCapture}
                  customFieldDefinitions={customFieldDefinitions}
                  onUpdateExtra={onUpdateExtra ? (extra) => onUpdateExtra(item, extra) : undefined}
                />
              ))}
              {items.length === 0 && (
                <p className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  {lots.length > 0
                    ? "Aucun article individuel disponible. Ajoutez un lot pour préparer du matériel."
                    : vehicleType === "secours_a_personne"
                      ? "Aucun matériel disponible. Gérez vos articles depuis l'inventaire pharmacie pour les rendre disponibles ici."
                      : "Aucun matériel disponible. Gérez vos articles depuis l'inventaire remises pour les rendre disponibles ici."}
                </p>
              )}
              {items.length > 0 && filteredItems.length === 0 && (
                <p className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  Aucun matériel ne correspond à la recherche.
                </p>
              )}
            </div>
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
  onUpdateQuantity?: (quantity: number) => void;
  onDragStartCapture?: () => void;
  customFieldDefinitions?: CustomFieldDefinition[];
  onUpdateExtra?: (extra: Record<string, unknown>) => void;
}

function areExtraValuesEqual(
  current: Record<string, unknown> = {},
  next: Record<string, unknown> = {}
) {
  const isPlainObject = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);

  const areArraysEqual = (left: unknown[], right: unknown[]) => {
    if (left.length !== right.length) {
      return false;
    }
    return left.every((value, index) => isExtraValueEqual(value, right[index]));
  };

  const isExtraValueEqual = (left: unknown, right: unknown): boolean => {
    if (Object.is(left, right)) {
      return true;
    }
    if (Array.isArray(left) && Array.isArray(right)) {
      return areArraysEqual(left, right);
    }
    if (isPlainObject(left) && isPlainObject(right)) {
      const leftKeys = Object.keys(left);
      const rightKeys = Object.keys(right);
      if (leftKeys.length !== rightKeys.length) {
        return false;
      }
      return leftKeys.every((key) => Object.is(left[key], right[key]));
    }
    return false;
  };

  const currentKeys = Object.keys(current);
  const nextKeys = Object.keys(next);
  if (currentKeys.length !== nextKeys.length) {
    return false;
  }
  return currentKeys.every((key) => isExtraValueEqual(current[key], next[key]));
}

function ItemCard({
  item,
  onRemove,
  onFeedback,
  onUpdatePosition,
  onUpdateQuantity,
  onDragStartCapture,
  customFieldDefinitions = [],
  onUpdateExtra
}: ItemCardProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const renderCountRef = useRef(0);
  renderCountRef.current += 1;
  if (import.meta.env.DEV) {
    console.debug("[ItemCard] render", { itemId: item.id, count: renderCountRef.current });
  }
  const [isEditingPosition, setIsEditingPosition] = useState(false);
  const [draftPosition, setDraftPosition] = useState(() => ({
    x: Math.round(clamp((item.position_x ?? 0.5) * 100, 0, 100)),
    y: Math.round(clamp((item.position_y ?? 0.5) * 100, 0, 100))
  }));
  const [draftQuantity, setDraftQuantity] = useState(item.quantity);
  const [isSavingQuantity, setIsSavingQuantity] = useState(false);
  const [isEditingExtra, setIsEditingExtra] = useState(false);
  const [extraDraft, setExtraDraft] = useState<Record<string, unknown>>(() =>
    buildCustomFieldDefaults(customFieldDefinitions, item.extra ?? {})
  );

  const imageUrl = resolveMediaUrl(item.image_url);
  const hasImage = Boolean(imageUrl);

  const availableQuantity = getAvailableQuantity(item);
  const quantityLabel =
    item.category_id === null
      ? item.pharmacy_item_id !== null
        ? `Stock pharmacie : ${availableQuantity}`
        : `Stock remise : ${availableQuantity}`
      : `Qté : ${item.quantity}`;
  const isLockedByLot = item.lot_id !== null;
  const lotLabel = isLockedByLot ? item.lot_name ?? `Lot #${item.lot_id}` : null;

  useEffect(() => {
    if (isEditingPosition) {
      return;
    }
    // Garder le brouillon aligné aux props sans réécriture inutile.
    const nextDraft = {
      x: Math.round(clamp((item.position_x ?? 0.5) * 100, 0, 100)),
      y: Math.round(clamp((item.position_y ?? 0.5) * 100, 0, 100))
    };
    setDraftPosition((previous) => {
      const shouldUpdate = previous.x !== nextDraft.x || previous.y !== nextDraft.y;
      if (import.meta.env.DEV) {
        console.debug("[ItemCard] position sync effect", {
          itemId: item.id,
          shouldUpdate,
          nextDraft
        });
      }
      return shouldUpdate ? nextDraft : previous;
    });
  }, [item.position_x, item.position_y, isEditingPosition]);

  useEffect(() => {
    // Évite de relancer un rendu si la quantité n'a pas changé.
    setDraftQuantity((previous) => {
      const shouldUpdate = previous !== item.quantity;
      if (import.meta.env.DEV) {
        console.debug("[ItemCard] quantity sync effect", {
          itemId: item.id,
          shouldUpdate,
          nextQuantity: item.quantity
        });
      }
      return shouldUpdate ? item.quantity : previous;
    });
    setIsSavingQuantity((previous) => (previous ? false : previous));
  }, [item.quantity]);

  useEffect(() => {
    // Recalcule uniquement si les valeurs diffèrent pour éviter les boucles de rendu.
    const nextExtra = buildCustomFieldDefaults(customFieldDefinitions, item.extra ?? {});
    setExtraDraft((previous) => {
      const shouldUpdate = !areExtraValuesEqual(previous, nextExtra);
      if (import.meta.env.DEV) {
        console.debug("[ItemCard] extra sync effect", {
          itemId: item.id,
          shouldUpdate,
          nextExtraKeys: Object.keys(nextExtra)
        });
      }
      return shouldUpdate ? nextExtra : previous;
    });
  }, [customFieldDefinitions, item.extra]);

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

  const handleQuantityInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    event.stopPropagation();
    const rawValue = Number(event.target.value);
    const sanitized = Number.isNaN(rawValue) ? 0 : Math.round(rawValue);
    setDraftQuantity(clamp(sanitized, 0, 100000));
  };

  const handleQuantityStep = (delta: number) => () => {
    setDraftQuantity((previous) => clamp(Math.round(previous + delta), 0, 100000));
  };

  const handleQuantitySubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!onUpdateQuantity) {
      return;
    }
    const normalized = clamp(Math.round(draftQuantity), 0, 100000);
    if (normalized === item.quantity) {
      return;
    }
    setIsSavingQuantity(true);
    onUpdateQuantity(normalized);
  };

  const canEditQuantity = Boolean(onUpdateQuantity) && !isLockedByLot && item.category_id !== null;
  const isQuantityDirty = draftQuantity !== item.quantity;

  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600"
      draggable={!isEditingPosition}
      onDragStart={(event) => {
        if (isEditingPosition) {
          event.preventDefault();
          return;
        }
        onDragStartCapture?.();
        writeItemDragPayload(event, {
          id: item.id,
          category_id: item.category_id,
          remise_item_id: item.remise_item_id,
          pharmacy_item_id: item.pharmacy_item_id,
          lot_id: item.lot_id,
          lot_name: item.lot_name,
          quantity: item.quantity,
          available_quantity: item.available_quantity ?? null
        });
      }}
    >
      <AppTextInput
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
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Taille / Variante : {item.size ?? "—"}
          </p>
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
      {canEditQuantity ? (
        <form
          className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600 dark:border-slate-600/70 dark:bg-slate-800/40 dark:text-slate-200"
          onSubmit={handleQuantitySubmit}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-slate-700 dark:text-slate-100">Quantité affectée</span>
            <span className="text-[10px] text-slate-500 dark:text-slate-300">Mise à jour du stock liée</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-stretch overflow-hidden rounded-md border border-slate-300 bg-white text-slate-700 shadow-sm dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100">
              <button
                type="button"
                onClick={handleQuantityStep(-1)}
                className="px-3 text-sm font-semibold hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-slate-800"
              >
                −
              </button>
              <AppTextInput
                type="number"
                min={0}
                value={draftQuantity}
                onChange={handleQuantityInputChange}
                className="w-20 border-x border-slate-200 bg-white px-2 text-center text-xs text-slate-700 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
              <button
                type="button"
                onClick={handleQuantityStep(1)}
                className="px-3 text-sm font-semibold hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-slate-800"
              >
                +
              </button>
            </div>
            <button
              type="submit"
              disabled={!isQuantityDirty || isSavingQuantity}
              className="rounded-full border border-blue-200 px-3 py-1 text-[11px] font-medium text-blue-600 transition hover:border-blue-300 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-60 dark:border-blue-500/50 dark:text-blue-200 dark:hover:border-blue-400"
            >
              {isSavingQuantity ? "Enregistrement..." : "Mettre à jour"}
            </button>
          </div>
          <p className="text-[10px] text-slate-500 dark:text-slate-400">
            Ajustez la quantité présente dans cette vue : le stock de la remise associée sera mis à jour automatiquement.
          </p>
        </form>
      ) : null}
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
                  <AppTextInput
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
                  <AppTextInput
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
      {customFieldDefinitions.length > 0 ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600 dark:border-slate-600/70 dark:bg-slate-800/40 dark:text-slate-200">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-slate-600 dark:text-slate-200">
              Champs personnalisés
            </span>
            <button
              type="button"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setIsEditingExtra((previous) => !previous);
              }}
              className="rounded-full border border-slate-300 px-3 py-1 font-medium transition hover:border-slate-400 hover:text-slate-800 dark:border-slate-500 dark:hover:border-slate-400"
            >
              {isEditingExtra ? "Fermer" : "Modifier"}
            </button>
          </div>
          {isEditingExtra ? (
            <form
              className="mt-3 space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onUpdateExtra?.(extraDraft);
                setIsEditingExtra(false);
              }}
            >
              <CustomFieldsForm
                definitions={customFieldDefinitions}
                values={extraDraft}
                onChange={setExtraDraft}
              />
              <div className="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setExtraDraft(buildCustomFieldDefaults(customFieldDefinitions, item.extra ?? {}));
                    setIsEditingExtra(false);
                  }}
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
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function buildVehicleMarkerEntries(
  items: VehicleItem[],
  appliedLots: VehicleAppliedLot[] = [],
  appliedLotItemsByAssignment: Map<number, VehicleItem[]> = new Map()
): VehicleMarkerEntry[] {
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
  const markers: VehicleMarkerEntry[] = appliedLots.map((lot) =>
    createMarkerFromAppliedLot(lot, appliedLotItemsByAssignment.get(lot.id) ?? [])
  );
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

  for (const entry of entries) {
    layout.set(entry.key, {
      x: clamp(entry.position_x ?? 0.5, 0, 1),
      y: clamp(entry.position_y ?? 0.5, 0, 1)
    });
  }

  return layout;
}

function createMarkerFromItem(item: VehicleItem): VehicleMarkerEntry {
  return {
    key: `item-${item.id}`,
    kind: "item",
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
    remise_item_id: item.remise_item_id,
    pharmacy_item_id: item.pharmacy_item_id
  };
}

function createMarkerFromLotGroup(
  lotId: number,
  lotItems: VehicleItem[]
): VehicleMarkerEntry {
  const [representative] = lotItems;
  const lotName = representative?.lot_name ?? `Lot #${lotId}`;
  const totalQuantity = lotItems.reduce((sum, entry) => sum + entry.quantity, 0);
  const imageUrl = lotItems.find((entry) => Boolean(entry.image_url))?.image_url ?? null;
  const tooltip =
    lotItems.length > 0
      ? lotItems.map((entry) => `${entry.quantity} × ${entry.name}`).join("\n")
      : "Ce lot est encore vide.";
  const { x, y } = computeLotAveragePosition(lotItems);

  return {
    key: `lot-${lotId}`,
    kind: "lot",
    name: lotName,
    quantity: totalQuantity,
    image_url: imageUrl,
    position_x: x,
    position_y: y,
    lot_id: lotId,
    lot_name: lotName,
    lotItemIds: lotItems.map((entry) => entry.id),
    tooltip,
    isLot: true,
    primaryItemId: representative?.id ?? null,
    category_id: representative?.category_id ?? null,
    remise_item_id: representative?.remise_item_id ?? null,
    pharmacy_item_id: representative?.pharmacy_item_id ?? null
  };
}

function createMarkerFromAppliedLot(
  appliedLot: VehicleAppliedLot,
  appliedLotItems: VehicleItem[]
): VehicleMarkerEntry {
  const lotName = appliedLot.lot_name ?? "Lot pharmacie";
  const totalQuantity = appliedLotItems.reduce((sum, entry) => sum + entry.quantity, 0);
  const tooltip =
    appliedLotItems.length > 0
      ? appliedLotItems.map((entry) => `${entry.quantity} × ${entry.name}`).join("\n")
      : "Ce lot est encore vide.";

  return {
    key: `applied-lot-${appliedLot.id}`,
    kind: "applied_lot",
    name: lotName,
    quantity: totalQuantity,
    image_url: null,
    position_x: appliedLot.position_x,
    position_y: appliedLot.position_y,
    lot_id: null,
    lot_name: null,
    lotItemIds: appliedLotItems.map((entry) => entry.id),
    tooltip,
    isLot: true,
    primaryItemId: appliedLotItems[0]?.id ?? null,
    category_id: appliedLot.vehicle_id ?? null,
    remise_item_id: null,
    pharmacy_item_id: null,
    applied_lot_id: appliedLot.id,
    applied_lot_source: appliedLot.source,
    applied_lot_items: appliedLotItems
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
  const rawData =
    event.dataTransfer.getData("application/json") ||
    event.dataTransfer.getData("text/plain");
  if (!rawData) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawData) as Partial<DraggedItemData>;
    const isDragKind = (value: unknown): value is DragKind =>
      value === "library_item" ||
      value === "pharmacy_lot" ||
      value === "remise_lot" ||
      value === "applied_lot";
    if (!isDragKind(parsed.kind)) {
      return null;
    }
    const hasSourceType =
      parsed.sourceType === "vehicle" ||
      parsed.sourceType === "pharmacy" ||
      parsed.sourceType === "remise";
    const hasSourceId = typeof parsed.sourceId === "number";
    const hasLotId = typeof parsed.lotId === "number";
    const lotIdIsNull = parsed.lotId === null;
    const hasAppliedLotId = typeof parsed.appliedLotId === "number";
    if (
      (parsed.kind === "library_item" && (!hasSourceType || !hasSourceId)) ||
      ((parsed.kind === "pharmacy_lot" || parsed.kind === "remise_lot") && !hasLotId) ||
      (parsed.kind === "applied_lot" && !hasAppliedLotId)
    ) {
      return null;
    }
    return {
      kind: parsed.kind,
      sourceType: hasSourceType ? parsed.sourceType : undefined,
      sourceId: hasSourceId ? parsed.sourceId : undefined,
      vehicleItemId: typeof parsed.vehicleItemId === "number" ? parsed.vehicleItemId : undefined,
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
      pharmacyItemId:
        typeof parsed.pharmacyItemId === "number"
          ? parsed.pharmacyItemId
          : parsed.pharmacyItemId === null
            ? null
            : undefined,
      quantity: typeof parsed.quantity === "number" ? parsed.quantity : undefined,
      lotId: hasLotId ? parsed.lotId : lotIdIsNull ? null : undefined,
      lotName: typeof parsed.lotName === "string" ? parsed.lotName : undefined,
      appliedLotId: hasAppliedLotId ? parsed.appliedLotId : undefined,
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
}

export function normalizeVehicleViewsInput(rawInput: string): string[] {
  const entries = rawInput
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .map((entry) => normalizeViewName(entry));

  const uniqueEntries = Array.from(new Set(entries));

  return uniqueEntries.length > 0 ? uniqueEntries : [DEFAULT_VIEW_LABEL];
}

export function getVehicleViews(vehicle: VehicleCategory | null): string[] {
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

export function resolvePinnedView(
  views: string[],
  pinnedViewName: string | null
): string | null {
  if (!pinnedViewName) {
    return null;
  }
  const normalizedPinned = normalizeViewName(pinnedViewName);
  return (
    views.find((view) => normalizeViewName(view) === normalizedPinned) ?? null
  );
}

export function filterPinnedSubviews(params: {
  pinned: string[];
  availableSubViews: string[];
  parentView: string;
}): string[] {
  const normalizedParent = normalizeViewName(params.parentView);
  const normalizedAvailable = new Set(
    params.availableSubViews.map((view) => normalizeViewName(view))
  );
  const prefix = `${normalizedParent} - `;
  const filtered: string[] = [];
  const seen = new Set<string>();
  params.pinned.forEach((entry) => {
    if (!entry || entry.trim().length === 0) {
      return;
    }
    const normalized = normalizeViewName(entry);
    if (!normalized.startsWith(prefix)) {
      return;
    }
    if (!normalizedAvailable.has(normalized)) {
      return;
    }
    if (seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    filtered.push(normalized);
  });
  return filtered;
}

function normalizeViewNameStrict(name: string | null | undefined): string {
  if (!name) return "";
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, "")
    .replace(/\s+/g, " ");
}

export function normalizeViewName(view?: string | null): string {
  if (!view) {
    return DEFAULT_VIEW_LABEL;
  }

  const collapsedWhitespace = view.replace(/\s+/g, " ").trim();
  const standardizedHyphenSpacing = collapsedWhitespace.replace(/\s*-\s*/g, " - ");
  const withoutDiacritics = standardizedHyphenSpacing.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  return withoutDiacritics.toUpperCase();
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

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

import {
  InventoryModuleDashboard,
  type InventoryModuleConfig
} from "./InventoryModuleDashboard";
import { VehiclePhotosPanel } from "./VehiclePhotosPanel";

const VEHICLE_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire véhicules",
  description: "Suivez les véhicules disponibles, leurs mouvements et les catégories associées.",
  basePath: "/vehicle-inventory",
  categoriesPath: "/vehicle-inventory/categories",
  supplierModule: "vehicle_inventory",
  queryKeyPrefix: "vehicle-inventory",
  storageKeyPrefix: "vehicle-inventory",
  showPurchaseOrders: false,
  searchPlaceholder: "Rechercher un véhicule par nom ou SKU",
  supportsItemImages: true
};

export function VehicleInventoryPage() {
  return (
    <div className="space-y-6">
      <InventoryModuleDashboard config={VEHICLE_INVENTORY_CONFIG} />
      <VehiclePhotosPanel />
    </div>
  );
}

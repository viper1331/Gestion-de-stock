import {
  InventoryModuleDashboard,
  type InventoryModuleConfig
} from "./InventoryModuleDashboard";

const VEHICLE_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire véhicules",
  description: "Suivez les véhicules disponibles, leurs mouvements et les catégories associées.",
  basePath: "/vehicle-inventory",
  categoriesPath: "/vehicle-inventory/categories",
  supplierModule: "vehicle_inventory",
  queryKeyPrefix: "vehicle-inventory",
  storageKeyPrefix: "vehicle-inventory",
  showPurchaseOrders: false,
  searchPlaceholder: "Rechercher un véhicule par nom ou SKU"
};

export function VehicleInventoryPage() {
  return <InventoryModuleDashboard config={VEHICLE_INVENTORY_CONFIG} />;
}

import {
  InventoryModuleDashboard,
  type InventoryModuleConfig
} from "./InventoryModuleDashboard";

const REMISE_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire remises",
  description: "Gérez les stocks mis en remise, les ajustements et leur traçabilité.",
  basePath: "/remise-inventory",
  categoriesPath: "/remise-inventory/categories",
  supplierModule: "inventory_remise",
  queryKeyPrefix: "remise-inventory",
  storageKeyPrefix: "remise-inventory",
  showPurchaseOrders: false,
  searchPlaceholder: "Rechercher une remise par nom ou SKU",
  itemNoun: {
    singular: "matériel",
    plural: "matériels",
    gender: "masculine"
  }
};

export function RemiseInventoryPage() {
  return <InventoryModuleDashboard config={REMISE_INVENTORY_CONFIG} />;
}

import { InventoryModuleDashboard } from "./InventoryModuleDashboard";
import { RemiseLotsPanel } from "./RemiseLotsPanel";
import { type InventoryModuleConfig } from "./config";

const REMISE_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire remises",
  description: "Gérez les stocks mis en remise, les ajustements et leur traçabilité.",
  basePath: "/remise-inventory",
  categoriesPath: "/remise-inventory/categories",
  supplierModule: "inventory_remise",
  queryKeyPrefix: "remise-inventory",
  storageKeyPrefix: "remise-inventory",
  showPurchaseOrders: true,
  purchaseOrdersPath: "/remise-inventory/orders",
  purchaseOrdersItemsPath: "/remise-inventory",
  purchaseOrdersQueryKey: ["remise-purchase-orders"],
  purchaseOrdersItemsQueryKey: ["items"],
  purchaseOrdersTitle: "Bons de commande remises",
  purchaseOrdersDescription:
    "Suivez les commandes fournisseurs pour les remises et mettez à jour les stocks lors des réceptions.",
  purchaseOrdersDownloadPrefix: "bon_commande_remise",
  supportsLowStockOptOut: true,
  supportsExpirationDate: true,
  showVehicleTypeColumn: true,
  searchPlaceholder: "Rechercher une remise par nom ou SKU",
  barcodePrefix: "IS",
  itemNoun: {
    singular: "matériel",
    plural: "matériels",
    gender: "masculine"
  }
};

export function RemiseInventoryPage() {
  return (
    <div className="space-y-6">
      <InventoryModuleDashboard config={REMISE_INVENTORY_CONFIG} />
      <RemiseLotsPanel />
    </div>
  );
}

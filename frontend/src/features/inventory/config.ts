export type FrenchGender = "masculine" | "feminine";

export interface InventoryItemNounConfig {
  singular: string;
  plural?: string;
  gender: FrenchGender;
}

export interface InventoryModuleConfig {
  title: string;
  description: string;
  basePath: string;
  categoriesPath: string;
  supplierModule?: string | null;
  permissionsModuleKey?: string;
  queryKeyPrefix: string;
  storageKeyPrefix: string;
  tableKey?: string;
  showPurchaseOrders?: boolean;
  purchaseOrdersPath?: string;
  purchaseOrdersItemsPath?: string;
  purchaseOrdersQueryKey?: readonly unknown[];
  purchaseOrdersItemsQueryKey?: readonly unknown[];
  purchaseOrdersModuleKey?: string;
  purchaseOrdersTitle?: string;
  purchaseOrdersDescription?: string;
  purchaseOrdersDownloadPrefix?: string;
  purchaseOrdersItemIdField?: "item_id" | "remise_item_id" | "pharmacy_item_id";
  searchPlaceholder?: string;
  supportsItemImages?: boolean;
  supportsLowStockOptOut?: boolean;
  supportsExpirationDate?: boolean;
  showLotMembershipColumn?: boolean;
  itemNoun?: InventoryItemNounConfig;
  barcodePrefix?: string;
  barcodeModule?: "clothing" | "remise";
  exportPdfPath?: string;
  exportPdfFilenamePrefix?: string;
  customFieldScope?: string;
  statsPath?: string;
}

export const DEFAULT_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire",
  description:
    "Retrouvez l'ensemble des articles, appliquez des mouvements et gérez les catégories.",
  basePath: "/items",
  categoriesPath: "/categories",
  supplierModule: "suppliers",
  permissionsModuleKey: "clothing",
  queryKeyPrefix: "inventory",
  storageKeyPrefix: "inventory",
  tableKey: "clothing.items",
  showLotMembershipColumn: true,
  showPurchaseOrders: true,
  searchPlaceholder: "Rechercher par nom ou SKU",
  supportsItemImages: false,
  supportsLowStockOptOut: true,
  supportsExpirationDate: false,
  barcodePrefix: "HAB",
  statsPath: "/items/stats",
  barcodeModule: "clothing"
};

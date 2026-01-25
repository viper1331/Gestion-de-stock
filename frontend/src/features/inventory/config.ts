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
}

export const DEFAULT_INVENTORY_CONFIG: InventoryModuleConfig = {
  title: "Inventaire",
  description:
    "Retrouvez l'ensemble des articles, appliquez des mouvements et gérez les catégories.",
  basePath: "/items",
  categoriesPath: "/categories",
  supplierModule: "suppliers",
  queryKeyPrefix: "inventory",
  storageKeyPrefix: "inventory",
  tableKey: "clothing.items",
  showLotMembershipColumn: true,
  showPurchaseOrders: true,
  searchPlaceholder: "Rechercher par nom ou SKU",
  supportsItemImages: false,
  supportsExpirationDate: false,
  barcodePrefix: "HAB",
  barcodeModule: "clothing"
};

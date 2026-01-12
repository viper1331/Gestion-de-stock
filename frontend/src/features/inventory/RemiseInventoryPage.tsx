import { useMemo } from "react";

import { InventoryModuleDashboard } from "./InventoryModuleDashboard";
import { RemiseLotsPanel } from "./RemiseLotsPanel";
import { type InventoryModuleConfig } from "./config";
import { useModuleTitle } from "../../lib/moduleTitles";
import { EditablePageLayout, type EditableLayoutSet, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

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
  purchaseOrdersItemIdField: "remise_item_id",
  supportsLowStockOptOut: true,
  supportsExpirationDate: true,
  showLotMembershipColumn: true,
  searchPlaceholder: "Rechercher une remise par nom ou SKU",
  barcodePrefix: "IS",
  exportPdfPath: "/remise-inventory/export/pdf",
  exportPdfFilenamePrefix: "inventaire_remises",
  customFieldScope: "remise_items",
  itemNoun: {
    singular: "matériel",
    plural: "matériels",
    gender: "masculine"
  }
};

export function RemiseInventoryPage() {
  const moduleTitle = useModuleTitle("inventory_remise");
  const config = useMemo(
    () => ({ ...REMISE_INVENTORY_CONFIG, title: moduleTitle }),
    [moduleTitle]
  );

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [
        { i: "remise-inventory-dashboard", x: 0, y: 0, w: 12, h: 18 },
        { i: "remise-lots", x: 0, y: 18, w: 12, h: 12 }
      ],
      md: [
        { i: "remise-inventory-dashboard", x: 0, y: 0, w: 6, h: 18 },
        { i: "remise-lots", x: 0, y: 18, w: 6, h: 12 }
      ],
      sm: [
        { i: "remise-inventory-dashboard", x: 0, y: 0, w: 1, h: 18 },
        { i: "remise-lots", x: 0, y: 18, w: 1, h: 12 }
      ],
      xs: [
        { i: "remise-inventory-dashboard", x: 0, y: 0, w: 1, h: 18 },
        { i: "remise-lots", x: 0, y: 18, w: 1, h: 12 }
      ]
    }),
    []
  );

  const blocks = useMemo<EditablePageBlock[]>(
    () => [
      {
        id: "remise-inventory-dashboard",
        title: "Inventaire remises",
        required: true,
        permission: { module: "inventory_remise", action: "view" },
        containerClassName: "rounded-none border-0 bg-transparent p-0",
        render: () => (
          <EditableBlock id="remise-inventory-dashboard">
            <InventoryModuleDashboard config={config} />
          </EditableBlock>
        )
      },
      {
        id: "remise-lots",
        title: "Lots",
        permission: { module: "inventory_remise", action: "view" },
        minH: 12,
        containerClassName: "rounded-none border-0 bg-transparent p-0",
        render: () => (
          <EditableBlock id="remise-lots">
            <RemiseLotsPanel />
          </EditableBlock>
        )
      }
    ],
    [config]
  );

  return (
    <EditablePageLayout
      pageKey="module:remise:inventory"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      pagePermission={{ module: "inventory_remise", action: "view" }}
    />
  );
}

import { useMemo } from "react";

import { InventoryModuleDashboard } from "./InventoryModuleDashboard";
import { RemiseLotsPanel } from "./RemiseLotsPanel";
import { type InventoryModuleConfig } from "./config";
import { useModuleTitle } from "../../lib/moduleTitles";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
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

  const blocks = useMemo<EditablePageBlock[]>(
    () => [
      {
        id: "remise-inventory-dashboard",
        title: "Inventaire remises",
        required: true,
        permissions: ["inventory_remise"],
        variant: "plain",
        defaultLayout: {
          lg: { x: 0, y: 0, w: 12, h: 18 },
          md: { x: 0, y: 0, w: 10, h: 18 },
          sm: { x: 0, y: 0, w: 6, h: 18 },
          xs: { x: 0, y: 0, w: 4, h: 18 }
        },
        render: () => (
          <EditableBlock id="remise-inventory-dashboard">
            <InventoryModuleDashboard config={config} />
          </EditableBlock>
        )
      },
      {
        id: "remise-lots",
        title: "Lots",
        permissions: ["inventory_remise"],
        variant: "plain",
        minH: 10,
        defaultLayout: {
          lg: { x: 0, y: 18, w: 12, h: 14 },
          md: { x: 0, y: 18, w: 10, h: 14 },
          sm: { x: 0, y: 18, w: 6, h: 14 },
          xs: { x: 0, y: 18, w: 4, h: 14 }
        },
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
    />
  );
}

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
  tableKey: "remise.items",
  showPurchaseOrders: true,
  purchaseOrdersPath: "/remise-inventory/orders",
  purchaseOrdersItemsPath: "/remise-inventory",
  purchaseOrdersQueryKey: ["remise-purchase-orders"],
  purchaseOrdersItemsQueryKey: ["items"],
  purchaseOrdersModuleKey: "inventory_remise",
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

  return (
    <InventoryModuleDashboard
      config={config}
      renderLayout={({ header, filters, table, orders }) => {
        const blocks: EditablePageBlock[] = [
          {
            id: "remise-header",
            title: "Inventaire remises",
            required: true,
            permissions: ["inventory_remise"],
            variant: "plain",
            defaultLayout: {
              lg: { x: 0, y: 0, w: 12, h: 6 },
              md: { x: 0, y: 0, w: 10, h: 6 },
              sm: { x: 0, y: 0, w: 6, h: 6 },
              xs: { x: 0, y: 0, w: 4, h: 6 }
            },
            render: () => (
              <EditableBlock id="remise-header">
                {header}
              </EditableBlock>
            )
          },
          {
            id: "remise-filters",
            title: "Filtres et actions",
            permissions: ["inventory_remise"],
            variant: "plain",
            defaultLayout: {
              lg: { x: 0, y: 6, w: 12, h: 6 },
              md: { x: 0, y: 6, w: 10, h: 6 },
              sm: { x: 0, y: 6, w: 6, h: 6 },
              xs: { x: 0, y: 6, w: 4, h: 6 }
            },
            render: () => (
              <EditableBlock id="remise-filters">
                {filters}
              </EditableBlock>
            )
          },
          {
            id: "remise-items",
            title: "Matériels en remise",
            permissions: ["inventory_remise"],
            variant: "plain",
            defaultLayout: {
              lg: { x: 0, y: 12, w: 12, h: 20 },
              md: { x: 0, y: 12, w: 10, h: 20 },
              sm: { x: 0, y: 12, w: 6, h: 20 },
              xs: { x: 0, y: 12, w: 4, h: 20 }
            },
            render: () => (
              <EditableBlock id="remise-items">
                {table}
              </EditableBlock>
            )
          }
        ];

        if (orders) {
          blocks.push({
            id: "remise-orders",
            title: "Bons de commande remises",
            permissions: ["inventory_remise"],
            variant: "plain",
            minH: 12,
            defaultLayout: {
              lg: { x: 0, y: 32, w: 12, h: 12 },
              md: { x: 0, y: 32, w: 10, h: 12 },
              sm: { x: 0, y: 32, w: 6, h: 12 },
              xs: { x: 0, y: 32, w: 4, h: 12 }
            },
            render: () => (
              <EditableBlock id="remise-orders">
                {orders}
              </EditableBlock>
            )
          });
        }

        blocks.push({
          id: "remise-lots",
          title: "Lots",
          permissions: ["inventory_remise"],
          variant: "plain",
          minH: 10,
          defaultLayout: {
            lg: { x: 0, y: 44, w: 12, h: 14 },
            md: { x: 0, y: 44, w: 10, h: 14 },
            sm: { x: 0, y: 44, w: 6, h: 14 },
            xs: { x: 0, y: 44, w: 4, h: 14 }
          },
          render: () => (
            <EditableBlock id="remise-lots">
              <RemiseLotsPanel />
            </EditableBlock>
          )
        });

        return (
          <EditablePageLayout
            pageKey="module:remise:inventory"
            blocks={blocks}
            renderHeader={({ editButton, actionButtons, isEditing }) => (
              <div className="flex flex-wrap justify-end gap-2">
                {editButton}
                {isEditing ? actionButtons : null}
              </div>
            )}
          />
        );
      }}
    />
  );
}

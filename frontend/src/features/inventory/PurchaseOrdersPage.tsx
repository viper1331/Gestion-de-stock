import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";
import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

interface Supplier {
  id: number;
  name: string;
  email: string | null;
  address: string | null;
}

export function PurchaseOrdersPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("clothing");
  const canViewSuppliers = user?.role === "admin" || modulePermissions.canAccess("suppliers");

  const { data: suppliers = [], isFetching } = useQuery({
    queryKey: ["suppliers", { module: "suppliers" }],
    queryFn: async () => {
      const response = await api.get<Supplier[]>("/suppliers/", {
        params: { module: "suppliers" }
      });
      return response.data;
    },
    enabled: canView && canViewSuppliers
  });

  const gateContent = (() => {
    if (modulePermissions.isLoading && user?.role !== "admin") {
      return (
        <section className="space-y-4">
          <header className="space-y-1">
            <h2 className="text-2xl font-semibold text-white">Bons de commande</h2>
            <p className="text-sm text-slate-400">Centralisez la création, le suivi et la réception.</p>
          </header>
          <p className="text-sm text-slate-400">Vérification des permissions...</p>
        </section>
      );
    }

    if (!canView) {
      return (
        <section className="space-y-4">
          <header className="space-y-1">
            <h2 className="text-2xl font-semibold text-white">Bons de commande</h2>
            <p className="text-sm text-slate-400">Centralisez la création, le suivi et la réception.</p>
          </header>
          <p className="text-sm text-red-400">Accès refusé.</p>
        </section>
      );
    }

    return null;
  })();

  const blocks = useMemo<EditablePageBlock[]>(
    () => [
      {
        id: "purchase-orders-panel",
        title: "Bons de commande",
        permissions: ["clothing"],
        required: true,
        variant: "plain",
        defaultLayout: {
          lg: { x: 0, y: 0, w: 12, h: 14 },
          md: { x: 0, y: 0, w: 10, h: 14 },
          sm: { x: 0, y: 0, w: 6, h: 14 },
          xs: { x: 0, y: 0, w: 4, h: 14 }
        },
        render: () => (
          <EditableBlock id="purchase-orders-panel">
            {gateContent ? gateContent : <PurchaseOrdersPanel suppliers={suppliers} />}
          </EditableBlock>
        )
      }
    ],
    [gateContent, suppliers]
  );

  return (
    <EditablePageLayout
      pageKey="module:clothing:purchase-orders"
      blocks={blocks}
      renderHeader={({ editButton, actionButtons, isEditing }) => (
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Bons de commande</h2>
          <p className="text-sm text-slate-400">
            Centralisez la création, le suivi et la réception de vos bons de commande.
          </p>
          {isFetching ? <p className="text-xs text-slate-500">Chargement des fournisseurs...</p> : null}
          {!canViewSuppliers && user?.role !== "admin" ? (
            <p className="text-xs text-amber-400">
              Les fournisseurs ne sont pas accessibles sans l'autorisation dédiée.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2 pt-2">
            {editButton}
            {isEditing ? actionButtons : null}
          </div>
        </header>
      )}
    />
  );
}

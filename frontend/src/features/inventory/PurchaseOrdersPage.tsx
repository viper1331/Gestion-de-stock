import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";
import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import {
  EditablePageLayout,
  type EditableLayoutSet,
  type EditablePageBlock
} from "../../components/EditablePageLayout";

interface Supplier {
  id: number;
  name: string;
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

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [{ i: "purchase-orders-panel", x: 0, y: 0, w: 12, h: 12 }],
      md: [{ i: "purchase-orders-panel", x: 0, y: 0, w: 6, h: 12 }],
      sm: [{ i: "purchase-orders-panel", x: 0, y: 0, w: 1, h: 12 }]
    }),
    []
  );

  const blocks = useMemo<EditablePageBlock[]>(
    () => [
      {
        id: "purchase-orders-panel",
        title: "Bons de commande",
        permission: { module: "clothing", action: "view" },
        render: () => <PurchaseOrdersPanel suppliers={suppliers} />
      }
    ],
    [suppliers]
  );

  return (
    <EditablePageLayout
      pageId="module:clothing:purchase-orders"
      blocks={blocks}
      defaultLayouts={defaultLayouts}
      pagePermission={{ module: "clothing", action: "view" }}
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

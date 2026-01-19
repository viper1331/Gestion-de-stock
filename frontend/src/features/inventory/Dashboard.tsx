import { useMemo } from "react";

import { InventoryModuleDashboard } from "./InventoryModuleDashboard";
import { DEFAULT_INVENTORY_CONFIG } from "./config";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";

export { InventoryModuleDashboard } from "./InventoryModuleDashboard";
export type { InventoryModuleConfig } from "./config";

export function Dashboard() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const moduleTitle = useModuleTitle("clothing");
  const canView = user?.role === "admin" || modulePermissions.canAccess("clothing");

  const inventoryConfig = useMemo(
    () => ({
      ...DEFAULT_INVENTORY_CONFIG,
      title: moduleTitle,
      exportPdfPath: "/stock/pdf/export",
      exportPdfFilenamePrefix: "inventaire_habillement"
    }),
    [moduleTitle]
  );

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gestion des articles, mouvements et catégories.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gestion des articles, mouvements et catégories.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  return <InventoryModuleDashboard config={inventoryConfig} />;
}

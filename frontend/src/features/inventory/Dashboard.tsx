import { InventoryModuleDashboard, DEFAULT_INVENTORY_CONFIG } from "./InventoryModuleDashboard";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

export { InventoryModuleDashboard } from "./InventoryModuleDashboard";
export type { InventoryModuleConfig } from "./InventoryModuleDashboard";

export function Dashboard() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("clothing");

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Inventaire habillement</h2>
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
          <h2 className="text-2xl font-semibold text-white">Inventaire habillement</h2>
          <p className="text-sm text-slate-400">Gestion des articles, mouvements et catégories.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  return <InventoryModuleDashboard config={DEFAULT_INVENTORY_CONFIG} />;
}

import { InventoryModuleDashboard, DEFAULT_INVENTORY_CONFIG } from "./InventoryModuleDashboard";

export { InventoryModuleDashboard } from "./InventoryModuleDashboard";
export type { InventoryModuleConfig } from "./InventoryModuleDashboard";

export function Dashboard() {
  return <InventoryModuleDashboard config={DEFAULT_INVENTORY_CONFIG} />;
}

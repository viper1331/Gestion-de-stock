import { useCallback, useMemo } from "react";

import { useAuth } from "../auth/useAuth";

const INVENTORY_DEBUG_ENABLED =
  String(
    import.meta.env.VITE_INVENTORY_DEBUG ??
      // Fallback for environments that don't inject the VITE_ prefix.
      import.meta.env.INVENTORY_DEBUG ??
      "false"
  )
    .toLowerCase()
    .trim() === "true";

export function useInventoryDebug() {
  const { user } = useAuth();

  const isEnabled = useMemo(
    () => user?.role === "admin" || INVENTORY_DEBUG_ENABLED,
    [user?.role]
  );

  const logDebug = useCallback(
    (message: string, data?: unknown) => {
      if (!isEnabled) {
        return;
      }
      console.debug("[INVENTORY_DEBUG]", message, data ?? "");
    },
    [isEnabled]
  );

  const logDragEvent = useCallback(
    (eventName: string, details?: Record<string, unknown>) => {
      if (!isEnabled) {
        return;
      }
      console.log(`[VehicleInventory] ${eventName}`, details ?? {});
    },
    [isEnabled]
  );

  return { isEnabled, logDebug, logDragEvent };
}

// useInventoryDebug.ts
export function useInventoryDebug(enabled: boolean) {
  if (!enabled) {
    const noop = () => {};
    return {
      logInfo: noop,
      logWarn: noop,
      logError: noop,
      logDrop: noop,
      logHover: noop,
    };
  }

  return {
    logInfo: (...args: any[]) => console.info("[INVENTORY_DEBUG]", ...args),
    logWarn: (...args: any[]) => console.warn("[INVENTORY_DEBUG]", ...args),
    logError: (...args: any[]) => console.error("[INVENTORY_DEBUG]", ...args),
    logDrop: (...args: any[]) => console.debug("[DROP_EVENT]", ...args),
    logHover: (...args: any[]) => console.debug("[HOVER]", ...args),
  };
}

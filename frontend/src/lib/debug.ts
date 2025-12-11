import { useSyncExternalStore } from "react";

export type DebugFlagKey = "frontend_debug" | "backend_debug" | "inventory_debug" | "network_debug";

export type DebugFlags = Record<DebugFlagKey, boolean>;

const DEBUG_EVENT = "gsp:debug-flags-changed";

export const DEFAULT_DEBUG_FLAGS: DebugFlags = {
  frontend_debug: false,
  backend_debug: false,
  inventory_debug: false,
  network_debug: false
};

export const isDebugEnabled = (name: DebugFlagKey): boolean => {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(name) === "1";
};

const emitDebugChange = () => {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new Event(DEBUG_EVENT));
};

export const persistDebugFlags = (flags: DebugFlags) => {
  if (typeof window === "undefined") {
    return;
  }
  (Object.keys(flags) as DebugFlagKey[]).forEach((key) => {
    window.localStorage.setItem(key, flags[key] ? "1" : "0");
  });
  emitDebugChange();
};

const readDebugFlags = (): DebugFlags => {
  if (typeof window === "undefined") {
    return DEFAULT_DEBUG_FLAGS;
  }
  return {
    frontend_debug: isDebugEnabled("frontend_debug"),
    backend_debug: isDebugEnabled("backend_debug"),
    inventory_debug: isDebugEnabled("inventory_debug"),
    network_debug: isDebugEnabled("network_debug")
  };
};

const subscribeToDebugChanges = (onChange: () => void) => {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  window.addEventListener(DEBUG_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(DEBUG_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
};

export const useDebugFlags = () =>
  useSyncExternalStore(subscribeToDebugChanges, () => readDebugFlags(), () => DEFAULT_DEBUG_FLAGS);

export function debugLog(type: string, payload: unknown) {
  if (isDebugEnabled("frontend_debug")) {
    // eslint-disable-next-line no-console
    console.debug(`[FRONTEND_DEBUG] ${type}`, payload);
  }
}

export function invDebug(message: string, payload?: unknown) {
  if (isDebugEnabled("inventory_debug")) {
    // eslint-disable-next-line no-console
    console.debug("[INVENTORY_DEBUG]", message, payload ?? "");
  }
}

export function apiDebug(message: string, payload?: unknown) {
  if (isDebugEnabled("network_debug")) {
    // eslint-disable-next-line no-console
    console.debug("[API_DEBUG]", message, payload ?? "");
  }
}

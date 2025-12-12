import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";

const LOG_THROTTLE_MS = 100;

interface DragEventPayload {
  selectedVehicleId?: number | null;
  selectedView?: string | null;
  itemId?: number | string | null;
  targetPosition?: { x?: number; y?: number } | null;
  backendView?: string | null;
  [key: string]: unknown;
}

const fetchInventoryDebugFlag = async (): Promise<boolean> => {
  try {
    const response = await api.get<{ inventory_debug?: boolean }>("/admin/debug-config");
    return Boolean(response.data?.inventory_debug);
  } catch {
    return false;
  }
};

const postLog = async (eventName: string, payload?: unknown) => {
  try {
    const userAgent = typeof navigator !== "undefined" ? navigator.userAgent : undefined;
    const url = typeof window !== "undefined" ? window.location.href : undefined;

    await api.post("/logs/frontend", {
      level: "debug",
      message: `[inventory] ${eventName}`,
      context: { event: eventName, source: "inventory", payload },
      user_agent: userAgent,
      url,
      timestamp: new Date().toISOString()
    });
  } catch {
    // Silent fallback: avoid surfacing any logging errors
  }
};

const normalizeDragPayload = (
  eventName: string,
  payload?: DragEventPayload
): DragEventPayload & { eventName: string } => ({
  selectedVehicleId: payload?.selectedVehicleId ?? null,
  selectedView: payload?.selectedView ?? null,
  itemId: payload?.itemId ?? null,
  targetPosition:
    payload?.targetPosition ??
    (typeof payload?.x === "number" && typeof payload?.y === "number"
      ? { x: payload.x, y: payload.y }
      : null),
  backendView: payload?.backendView ?? (payload as { targetView?: string })?.targetView ?? null,
  ...payload,
  eventName
});

export function useInventoryDebug(enabled: boolean) {
  const [backendEnabled, setBackendEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetchInventoryDebugFlag().then((flag) => {
      if (!cancelled) {
        setBackendEnabled(flag);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const isDebugActive = useMemo(() => enabled && backendEnabled, [backendEnabled, enabled]);

  const logDebug = useCallback(
    (eventName: string, payload?: unknown) => {
      if (!isDebugActive) {
        return;
      }
      try {
        // eslint-disable-next-line no-console
        console.debug(`[INVENTORY_DEBUG] ${eventName}`, payload ?? "");
      } catch {
        // Ignore console errors in restrictive environments
      }
      void postLog(eventName, payload);
    },
    [isDebugActive]
  );

  const lastDragLogRef = useRef(0);
  const queuedDragRef = useRef<(() => void) | null>(null);
  const throttleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (throttleTimerRef.current) {
        clearTimeout(throttleTimerRef.current);
      }
    };
  }, []);

  const logDragEvent = useCallback(
    (eventName: string, payload?: DragEventPayload) => {
      if (!isDebugActive) {
        return;
      }

      const emitLog = () => {
        const normalizedPayload = normalizeDragPayload(eventName, payload);

        try {
          // eslint-disable-next-line no-console
          console.debug(`[INVENTORY_DRAG] ${eventName}`, normalizedPayload);
        } catch {
          // Ignore console errors in restrictive environments
        }

        void postLog(eventName, normalizedPayload);
      };

      const now = Date.now();
      const elapsed = now - lastDragLogRef.current;

      if (elapsed >= LOG_THROTTLE_MS) {
        lastDragLogRef.current = now;
        emitLog();
        return;
      }

      queuedDragRef.current = emitLog;

      if (!throttleTimerRef.current) {
        throttleTimerRef.current = setTimeout(() => {
          throttleTimerRef.current = null;
          lastDragLogRef.current = Date.now();
          const queued = queuedDragRef.current;
          queuedDragRef.current = null;
          if (queued) {
            queued();
          }
        }, LOG_THROTTLE_MS - elapsed);
      }
    },
    [isDebugActive]
  );

  const logHover = useCallback(
    (payload?: DragEventPayload) => logDragEvent("dragover", payload),
    [logDragEvent]
  );

  const logDrop = useCallback(
    (payload?: DragEventPayload) => logDragEvent("drop", payload),
    [logDragEvent]
  );

  const legacyLogger = {
    logInfo: logDebug,
    logWarn: logDebug,
    logError: logDebug,
    logDrop,
    logHover
  };

  return { logDebug, logDragEvent, ...legacyLogger } as const;
}

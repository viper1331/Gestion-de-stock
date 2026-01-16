import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { useAuth } from "../features/auth/useAuth";
import { fetchPublicSystemConfig } from "../lib/systemConfig";

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "touchmove", "focus"];
const STORAGE_ACTIVITY_KEY = "gsp_last_activity_ts";
const STORAGE_LOGOUT_KEY = "gsp_auth_logout_at";
const CHECK_INTERVAL_MS = 5000;
const ACTIVITY_STORAGE_THROTTLE_MS = 1000;

type LogoutPayload = {
  ts: number;
  reason?: string | null;
};

const parseLogoutPayload = (value: string | null): LogoutPayload | null => {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as Partial<LogoutPayload>;
    if (typeof parsed.ts === "number") {
      return parsed as LogoutPayload;
    }
  } catch {
    return null;
  }
  return null;
};

export function useIdleLogout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const lastActivityRef = useRef<number>(Date.now());
  const lastStorageWriteRef = useRef<number>(0);
  const lastLogoutTsRef = useRef<number>(0);

  const { data: publicConfig } = useQuery({
    queryKey: ["system", "public-config"],
    queryFn: fetchPublicSystemConfig,
    enabled: Boolean(user)
  });

  const idleTimeoutMs = useMemo(() => {
    const minutes = publicConfig?.idle_logout_minutes ?? 0;
    if (!Number.isFinite(minutes) || minutes <= 0) {
      return null;
    }
    return minutes * 60_000;
  }, [publicConfig?.idle_logout_minutes]);

  useEffect(() => {
    if (!user || !idleTimeoutMs || location.pathname === "/login") {
      return undefined;
    }
    if (typeof window === "undefined") {
      return undefined;
    }

    const now = Date.now();
    const storedActivity = window.localStorage.getItem(STORAGE_ACTIVITY_KEY);
    const parsedActivity = storedActivity ? Number.parseInt(storedActivity, 10) : NaN;
    if (Number.isFinite(parsedActivity) && parsedActivity > 0) {
      lastActivityRef.current = Math.max(parsedActivity, now);
    } else {
      lastActivityRef.current = now;
    }

    const recordActivity = () => {
      const timestamp = Date.now();
      lastActivityRef.current = timestamp;
      if (typeof window === "undefined") {
        return;
      }
      if (timestamp - lastStorageWriteRef.current < ACTIVITY_STORAGE_THROTTLE_MS) {
        return;
      }
      lastStorageWriteRef.current = timestamp;
      window.localStorage.setItem(STORAGE_ACTIVITY_KEY, String(timestamp));
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_ACTIVITY_KEY && event.newValue) {
        const ts = Number.parseInt(event.newValue, 10);
        if (Number.isFinite(ts) && ts > lastActivityRef.current) {
          lastActivityRef.current = ts;
        }
      }
      if (event.key === STORAGE_LOGOUT_KEY && event.newValue) {
        const payload = parseLogoutPayload(event.newValue);
        if (!payload || !payload.ts || payload.ts === lastLogoutTsRef.current) {
          return;
        }
        lastLogoutTsRef.current = payload.ts;
        if (payload.reason === "idle") {
          logout({ reason: "idle" });
        } else {
          logout();
        }
      }
    };

    const intervalId = window.setInterval(() => {
      const idleDuration = Date.now() - lastActivityRef.current;
      if (idleDuration >= idleTimeoutMs) {
        logout({ reason: "idle" });
      }
    }, CHECK_INTERVAL_MS);

    ACTIVITY_EVENTS.forEach((eventName) => window.addEventListener(eventName, recordActivity));
    window.addEventListener("storage", handleStorage);
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        recordActivity();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    recordActivity();

    return () => {
      window.clearInterval(intervalId);
      ACTIVITY_EVENTS.forEach((eventName) => window.removeEventListener(eventName, recordActivity));
      window.removeEventListener("storage", handleStorage);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [idleTimeoutMs, location.pathname, logout, user]);
}

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { useAuth } from "../features/auth/useAuth";
import { AUTH_LOGOUT_EVENT } from "../features/auth/authEvents";
import {
  AUTH_LOGOUT_STORAGE_KEY,
  REFRESH_TOKEN_STORAGE_KEY
} from "../features/auth/authStorage";
import { fetchPublicSystemConfig } from "../lib/systemConfig";

const ACTIVITY_EVENTS = [
  "mousemove",
  "mousedown",
  "keydown",
  "scroll",
  "touchstart",
  "pointerdown",
  "wheel"
];
const CHECK_INTERVAL_MS = 5000;

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
  const { user, logout, logoutSilent } = useAuth();
  const location = useLocation();
  const lastLogoutTsRef = useRef<number>(0);
  const deadlineRef = useRef<number>(0);

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

  const logoutOnClose = Boolean(publicConfig?.logout_on_close);

  const resetDeadline = useCallback(() => {
    if (!idleTimeoutMs) {
      return;
    }
    deadlineRef.current = Date.now() + idleTimeoutMs;
  }, [idleTimeoutMs]);

  useEffect(() => {
    if (!user || !idleTimeoutMs || location.pathname === "/login") {
      return undefined;
    }
    if (typeof window === "undefined") {
      return undefined;
    }

    const recordActivity = () => {
      resetDeadline();
    };

    const intervalId = window.setInterval(() => {
      if (Date.now() > deadlineRef.current) {
        logout({ reason: "idle" });
      }
    }, CHECK_INTERVAL_MS);

    ACTIVITY_EVENTS.forEach((eventName) => window.addEventListener(eventName, recordActivity));
    recordActivity();

    return () => {
      window.clearInterval(intervalId);
      ACTIVITY_EVENTS.forEach((eventName) => window.removeEventListener(eventName, recordActivity));
    };
  }, [idleTimeoutMs, location.pathname, logout, resetDeadline, user]);

  useEffect(() => {
    if (!user || location.pathname === "/login") {
      return undefined;
    }
    if (typeof window === "undefined") {
      return undefined;
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key === AUTH_LOGOUT_STORAGE_KEY && event.newValue) {
        const payload = parseLogoutPayload(event.newValue);
        if (!payload || !payload.ts || payload.ts === lastLogoutTsRef.current) {
          return;
        }
        lastLogoutTsRef.current = payload.ts;
        logoutSilent();
        return;
      }
      if (event.key === REFRESH_TOKEN_STORAGE_KEY && event.newValue === null) {
        logoutSilent();
      }
    };

    const handleAuthLogout = () => {
      logoutSilent();
    };

    const handleBeforeUnload = () => {
      logoutSilent({ redirect: false });
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden" && logoutOnClose) {
        logoutSilent();
      }
    };

    window.addEventListener("storage", handleStorage);
    window.addEventListener(AUTH_LOGOUT_EVENT, handleAuthLogout);
    window.addEventListener("beforeunload", handleBeforeUnload);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener(AUTH_LOGOUT_EVENT, handleAuthLogout);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [location.pathname, logout, logoutOnClose, logoutSilent, user]);

  useEffect(() => {
    if (!user || !idleTimeoutMs) {
      return;
    }
    resetDeadline();
  }, [idleTimeoutMs, location.pathname, resetDeadline, user]);
}

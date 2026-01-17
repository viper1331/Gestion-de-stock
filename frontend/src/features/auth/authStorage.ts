export const REFRESH_TOKEN_STORAGE_KEY = "gsp/token";
export const AUTH_LOGOUT_STORAGE_KEY = "gsp_auth_logout_at";

export type RefreshTokenStorage = "local" | "session";

type LogoutPayload = {
  ts: number;
  reason?: string | null;
};

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) ?? window.sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
}

export function getRefreshTokenStorage(): RefreshTokenStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  if (window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)) {
    return "local";
  }
  if (window.sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)) {
    return "session";
  }
  return null;
}

export function storeRefreshToken(token: string, storage: RefreshTokenStorage) {
  if (typeof window === "undefined") {
    return;
  }
  if (storage === "local") {
    window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
    window.sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
  window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
}

export function clearStoredRefreshToken() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  window.sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
}

export function emitLogoutSignal(reason?: string | null) {
  if (typeof window === "undefined") {
    return;
  }
  const payload: LogoutPayload = {
    ts: Date.now(),
    reason: reason ?? null
  };
  window.localStorage.setItem(AUTH_LOGOUT_STORAGE_KEY, JSON.stringify(payload));
}

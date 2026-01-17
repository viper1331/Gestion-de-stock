export const AUTH_LOGOUT_EVENT = "gsp:auth-logout";

export type AuthLogoutReason = "unauthorized";

export function emitAuthLogout(reason: AuthLogoutReason) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_LOGOUT_EVENT, { detail: { reason } }));
}

import { useCallback, useMemo } from "react";
import { shallow } from "zustand/shallow";
import { useNavigate } from "react-router-dom";

import { api, setAccessToken, setAdminSiteOverride } from "../../lib/api";
import { queryClient } from "../../lib/queryClient";
import {
  clearStoredRefreshToken,
  emitLogoutSignal,
  getRefreshTokenStorage,
  getStoredRefreshToken,
  storeRefreshToken
} from "./authStorage";
import { useAuthStore, type UserProfile } from "./authStore";

interface LoginPayload {
  username: string;
  password: string;
  remember: boolean;
}

interface TwoFactorChallenge {
  status: "totp_required";
  challenge_token: string;
  user: {
    username: string;
    role: string;
    site_key: string | null;
  };
}

interface TwoFactorEnrollChallenge {
  status: "totp_enroll_required";
  challenge_token: string;
  otpauth_uri: string;
  secret_masked: string;
  secret_plain_if_allowed?: string | null;
  user: {
    username: string;
    role: string;
    site_key: string | null;
  };
}

type LoginResult =
  | { status: "authenticated" }
  | { status: "requires_2fa"; challenge: TwoFactorChallenge }
  | { status: "enroll_required"; challenge: TwoFactorEnrollChallenge }
  | { status: "error" };

const useAuthState = () =>
  useAuthStore(
    (state) => ({
      user: state.user,
      token: state.token,
      isLoading: state.isLoading,
      isCheckingSession: state.isCheckingSession,
      isReady: state.isReady,
      error: state.error,
      setAuth: state.setAuth,
      setLoading: state.setLoading,
      setChecking: state.setChecking,
      setReady: state.setReady,
      setError: state.setError,
      clear: state.clear
    }),
    shallow
  );

async function fetchProfile(): Promise<UserProfile> {
  const { data } = await api.get<UserProfile>("/auth/me");
  return data;
}

const getErrorDetail = (err: unknown): string | null => {
  if (typeof err === "object" && err && "response" in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response;
    return response?.data?.detail ?? null;
  }
  return null;
};

export function useAuth() {
  const navigate = useNavigate();
  const {
    user,
    token,
    isLoading,
    isCheckingSession,
    isReady,
    error,
    setAuth,
    setLoading,
    setChecking,
    setReady,
    setError,
    clear
  } = useAuthState();

  const completeLogin = useCallback(
    async (
      data: { access_token: string; refresh_token: string },
      remember: boolean
    ) => {
      setAccessToken(data.access_token);
      const profile = await fetchProfile();
      setAuth({
        user: profile,
        token: data.access_token,
        refreshToken: remember ? data.refresh_token : null
      });
      if (profile.role !== "admin") {
        setAdminSiteOverride(null);
      }
      storeRefreshToken(data.refresh_token, remember ? "local" : "session");
      navigate("/");
    },
    [navigate, setAuth]
  );

  const login = useCallback(
    async ({ username, password, remember }: LoginPayload): Promise<LoginResult> => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post<TwoFactorChallenge | TwoFactorEnrollChallenge>(
          "/auth/login",
          {
            username,
            password,
            remember_me: remember
          }
        );
        if ("status" in data && data.status === "totp_required") {
          setReady(true);
          return { status: "requires_2fa", challenge: data };
        }
        if ("status" in data && data.status === "totp_enroll_required") {
          setReady(true);
          return { status: "enroll_required", challenge: data };
        }
        setError("Réponse inattendue du serveur");
        return { status: "error" };
      } catch (err) {
        const detail = getErrorDetail(err);
        if (detail) {
          const lower = detail.toLowerCase();
          if (lower.includes("attente")) {
            setError("En attente de validation admin");
          } else if (lower.includes("refusé")) {
            setError("Compte refusé. Contactez un administrateur.");
          } else if (lower.includes("désactivé")) {
            setError("Compte désactivé.");
          } else {
            setError(detail);
          }
        } else {
          setError("Identifiants invalides");
        }
        return { status: "error" };
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [setError, setLoading, setReady]
  );

  const verifyTwoFactor = useCallback(
    async ({
      challengeId,
      code,
      rememberSession
    }: {
      challengeId: string;
      code: string;
      rememberSession: boolean;
    }) => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post("/auth/totp/verify", {
          challenge_token: challengeId,
          code
        });
        await completeLogin(data, rememberSession);
        return { status: "authenticated" };
      } catch (err) {
        const detail = getErrorDetail(err);
        if (detail?.toLowerCase().includes("expir")) {
          setError("Challenge expiré. Réessayez.");
        } else if (detail?.toLowerCase().includes("challenge")) {
          setError("Challenge invalide. Réessayez.");
        } else {
          setError("Code 2FA invalide");
        }
        return { status: "error" };
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [completeLogin, setError, setLoading, setReady]
  );

  const confirmTotpEnrollment = useCallback(
    async ({
      challengeToken,
      code,
      rememberSession
    }: {
      challengeToken: string;
      code: string;
      rememberSession: boolean;
    }) => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post("/auth/totp/enroll/confirm", {
          challenge_token: challengeToken,
          code
        });
        await completeLogin(data, rememberSession);
        return { status: "authenticated" };
      } catch (err) {
        const detail = getErrorDetail(err);
        if (detail?.toLowerCase().includes("expir")) {
          setError("Challenge expiré. Réessayez.");
        } else if (detail?.toLowerCase().includes("challenge")) {
          setError("Challenge invalide. Réessayez.");
        } else {
          setError("Code 2FA invalide");
        }
        return { status: "error" };
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [completeLogin, setError, setLoading, setReady]
  );

  const clearError = useCallback(() => {
    setError(null);
  }, [setError]);

  const initialize = useCallback(async () => {
    const currentState = useAuthStore.getState();
    if (currentState.isReady || currentState.isCheckingSession) {
      return;
    }
    setChecking(true);
    try {
      const storedRefresh = getStoredRefreshToken();
      const refreshStorage = getRefreshTokenStorage();
      if (!storedRefresh) {
        setReady(true);
        return;
      }
      const { data } = await api.post("/auth/refresh", { refresh_token: storedRefresh });
      setAccessToken(data.access_token);
      const profile = await fetchProfile();
      setAuth({ user: profile, token: data.access_token, refreshToken: data.refresh_token });
      if (profile.role !== "admin") {
        setAdminSiteOverride(null);
      }
      if (refreshStorage) {
        storeRefreshToken(data.refresh_token, refreshStorage);
      }
    } catch (error) {
      clearStoredRefreshToken();
      setAccessToken(null);
      setAdminSiteOverride(null);
      clear();
    } finally {
      setChecking(false);
      setReady(true);
    }
  }, [clear, setAuth, setChecking, setReady]);

  const performLogout = useCallback(
    (options?: { reason?: "idle"; redirect?: boolean; emitSignal?: boolean }) => {
      if (options?.emitSignal !== false) {
        emitLogoutSignal(options?.reason ?? null);
      }
      clear();
      setAccessToken(null);
      setAdminSiteOverride(null);
      clearStoredRefreshToken();
      queryClient.clear();
      setReady(true);
      const shouldRedirect =
        (options?.redirect ?? true) &&
        (typeof window === "undefined" || window.location.pathname !== "/login");
      if (!shouldRedirect) {
        return;
      }
      if (options?.reason) {
        navigate(`/login?reason=${options.reason}`);
        return;
      }
      navigate("/login");
    },
    [clear, navigate, setReady]
  );

  const logout = useCallback(
    (options?: { reason?: "idle" }) => {
      performLogout({ reason: options?.reason, emitSignal: true });
    },
    [performLogout]
  );

  const logoutSilent = useCallback(
    (options?: { redirect?: boolean }) => {
      performLogout({ redirect: options?.redirect, emitSignal: false });
    },
    [performLogout]
  );

  return useMemo(
    () => ({
      user,
      token,
      isLoading,
      error,
      isReady,
      isCheckingSession,
      login,
      verifyTwoFactor,
      confirmTotpEnrollment,
      clearError,
      logout,
      logoutSilent,
      initialize
    }),
    [
      error,
      initialize,
      isCheckingSession,
      isLoading,
      isReady,
      login,
      logout,
      logoutSilent,
      token,
      user,
      verifyTwoFactor,
      confirmTotpEnrollment,
      clearError
    ]
  );
}

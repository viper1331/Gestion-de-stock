import { useCallback, useMemo } from "react";
import { createWithEqualityFn } from "zustand/traditional";
import { shallow } from "zustand/shallow";
import { useNavigate } from "react-router-dom";

import { api, setAccessToken, setAdminSiteOverride } from "../../lib/api";

interface LoginPayload {
  username: string;
  password: string;
  remember: boolean;
}

interface TwoFactorChallenge {
  status?: string;
  requires_2fa?: boolean;
  challenge_id: string;
  available_methods: string[];
  username: string;
  trusted_device_supported?: boolean;
}

type LoginResult =
  | { status: "authenticated" }
  | { status: "requires_2fa"; challenge: TwoFactorChallenge }
  | { status: "2fa_setup_required" }
  | { status: "error" };

interface UserProfile {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  site_key: string;
}

interface AuthState {
  user: UserProfile | null;
  token: string | null;
  refreshToken: string | null;
  isLoading: boolean;
  isCheckingSession: boolean;
  isReady: boolean;
  error: string | null;
  setAuth: (params: { user: UserProfile; token: string; refreshToken: string | null }) => void;
  setLoading: (value: boolean) => void;
  setChecking: (value: boolean) => void;
  setReady: (value: boolean) => void;
  setError: (value: string | null) => void;
  clear: () => void;
}

export const useAuthStore = createWithEqualityFn<AuthState>()(
  (set) => ({
    user: null,
    token: null,
    refreshToken: null,
    isLoading: false,
    isCheckingSession: false,
    isReady: false,
    error: null,
    setAuth: ({ user, token, refreshToken }) =>
      set({ user, token, refreshToken, error: null }),
    setLoading: (value) => set({ isLoading: value }),
    setChecking: (value) => set({ isCheckingSession: value }),
    setReady: (value) => set({ isReady: value }),
    setError: (value) => set({ error: value }),
    clear: () => set({ user: null, token: null, refreshToken: null, error: null })
  }),
  shallow
);

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
      if (remember) {
        localStorage.setItem("gsp/token", data.refresh_token);
      } else {
        localStorage.removeItem("gsp/token");
      }
      navigate("/");
    },
    [navigate, setAuth]
  );

  const login = useCallback(
    async ({ username, password, remember }: LoginPayload): Promise<LoginResult> => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post<TwoFactorChallenge | { access_token: string; refresh_token: string }>(
          "/auth/login",
          {
            username,
            password,
            remember_me: remember
          }
        );
        if (
          ("status" in data && data.status === "totp_required") ||
          ("requires_2fa" in data && data.requires_2fa)
        ) {
          setReady(true);
          return { status: "requires_2fa", challenge: data };
        }
        if ("access_token" in data && "refresh_token" in data) {
          await completeLogin(data, remember);
          return { status: "authenticated" };
        }
        setError("Réponse inattendue du serveur");
        return { status: "error" };
      } catch (err) {
        const detail =
          typeof err === "object" && err && "response" in err
            ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : null;
        if (detail === "2FA_REQUIRED_SETUP") {
          setError("La 2FA est obligatoire. Activez-la pour continuer.");
          return { status: "2fa_setup_required" };
        }
        setError("Identifiants invalides");
        return { status: "error" };
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [completeLogin, setError, setLoading, setReady]
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
        const { data } = await api.post("/auth/2fa/verify", {
          challenge_id: challengeId,
          code,
          remember_device: false
        });
        await completeLogin(data, rememberSession);
        return { status: "authenticated" };
      } catch (err) {
        setError("Code 2FA invalide");
        return { status: "error" };
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [completeLogin, setError, setLoading, setReady]
  );

  const verifyRecoveryCode = useCallback(
    async ({
      challengeId,
      recoveryCode,
      rememberSession
    }: {
      challengeId: string;
      recoveryCode: string;
      rememberSession: boolean;
    }) => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post("/auth/2fa/recovery", {
          challenge_id: challengeId,
          recovery_code: recoveryCode,
          remember_device: false
        });
        await completeLogin(data, rememberSession);
        return { status: "authenticated" };
      } catch (err) {
        setError("Code de récupération invalide");
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
      const storedRefresh = localStorage.getItem("gsp/token");
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
      localStorage.setItem("gsp/token", data.refresh_token);
    } catch (error) {
      localStorage.removeItem("gsp/token");
      setAccessToken(null);
      setAdminSiteOverride(null);
      clear();
    } finally {
      setChecking(false);
      setReady(true);
    }
  }, [clear, setAuth, setChecking, setReady]);

  const logout = useCallback(() => {
    clear();
    setAccessToken(null);
    setAdminSiteOverride(null);
    localStorage.removeItem("gsp/token");
    setReady(true);
    navigate("/login");
  }, [clear, navigate, setReady]);

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
      verifyRecoveryCode,
      clearError,
      logout,
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
      token,
      user,
      verifyTwoFactor,
      verifyRecoveryCode,
      clearError
    ]
  );
}

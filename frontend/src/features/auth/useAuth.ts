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
        setError("Identifiants invalides");
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
      confirmTotpEnrollment,
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
      confirmTotpEnrollment,
      clearError
    ]
  );
}

import { useCallback, useMemo } from "react";
import { create } from "zustand";
import { shallow } from "zustand/shallow";
import { useNavigate } from "react-router-dom";

import { api, setAccessToken } from "../../lib/api";

interface LoginPayload {
  username: string;
  password: string;
  remember: boolean;
}

interface UserProfile {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
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

export const useAuthStore = create<AuthState>((set) => ({
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
}));

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

  const login = useCallback(
    async ({ username, password, remember }: LoginPayload) => {
      try {
        setLoading(true);
        setError(null);
        const { data } = await api.post("/auth/login", {
          username,
          password,
          remember_me: remember
        });
        setAccessToken(data.access_token);
        const profile = await fetchProfile();
        setAuth({
          user: profile,
          token: data.access_token,
          refreshToken: remember ? data.refresh_token : null
        });
        if (remember) {
          localStorage.setItem("gsp/token", data.refresh_token);
        } else {
          localStorage.removeItem("gsp/token");
        }
        navigate("/");
      } catch (err) {
        setError("Identifiants invalides");
      } finally {
        setLoading(false);
        setReady(true);
      }
    },
    [navigate, setAuth, setError, setLoading, setReady]
  );

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
      localStorage.setItem("gsp/token", data.refresh_token);
    } catch (error) {
      localStorage.removeItem("gsp/token");
      setAccessToken(null);
      clear();
    } finally {
      setChecking(false);
      setReady(true);
    }
  }, [clear, setAuth, setChecking, setReady]);

  const logout = useCallback(() => {
    clear();
    setAccessToken(null);
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
      logout,
      initialize
    }),
    [error, initialize, isCheckingSession, isLoading, isReady, login, logout, token, user]
  );
}

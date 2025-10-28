import { useCallback, useMemo } from "react";
import { create } from "zustand";
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

async function fetchProfile(): Promise<UserProfile> {
  const { data } = await api.get<UserProfile>("/auth/me");
  return data;
}

export function useAuth() {
  const navigate = useNavigate();
  const state = useAuthStore();

  const login = useCallback(
    async ({ username, password, remember }: LoginPayload) => {
      try {
        state.setLoading(true);
        state.setError(null);
        const { data } = await api.post("/auth/login", {
          username,
          password,
          remember_me: remember
        });
      setAccessToken(data.access_token);
      const profile = await fetchProfile();
      state.setAuth({
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
      state.setError("Identifiants invalides");
    } finally {
      state.setLoading(false);
      state.setReady(true);
    }
  },
  [navigate, state]
);

  const initialize = useCallback(async () => {
    const currentState = useAuthStore.getState();
    if (currentState.isReady || currentState.isCheckingSession) {
      return;
    }
    state.setChecking(true);
    try {
      const storedRefresh = localStorage.getItem("gsp/token");
      if (!storedRefresh) {
        state.setReady(true);
        return;
      }
      const { data } = await api.post("/auth/refresh", { refresh_token: storedRefresh });
      setAccessToken(data.access_token);
      const profile = await fetchProfile();
      state.setAuth({ user: profile, token: data.access_token, refreshToken: data.refresh_token });
      localStorage.setItem("gsp/token", data.refresh_token);
    } catch (error) {
      localStorage.removeItem("gsp/token");
      setAccessToken(null);
      state.clear();
    } finally {
      state.setChecking(false);
      state.setReady(true);
    }
  }, [state]);

  const logout = useCallback(() => {
    state.clear();
    setAccessToken(null);
    localStorage.removeItem("gsp/token");
    state.setReady(true);
    navigate("/login");
  }, [navigate, state]);

  return useMemo(
    () => ({
      user: state.user,
      token: state.token,
      isLoading: state.isLoading,
      error: state.error,
      isReady: state.isReady,
      isCheckingSession: state.isCheckingSession,
      login,
      logout,
      initialize
    }),
    [initialize, login, logout, state.error, state.isCheckingSession, state.isLoading, state.isReady, state.token, state.user]
  );
}

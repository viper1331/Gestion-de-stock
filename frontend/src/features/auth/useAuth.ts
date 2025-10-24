import { create } from "zustand";
import { useNavigate } from "react-router-dom";
import { useCallback } from "react";

import { api } from "../../lib/api";

interface LoginPayload {
  username: string;
  password: string;
  remember: boolean;
}

interface AuthState {
  user: { username: string; role: string } | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
  setAuth: (user: AuthState["user"], token: string) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoading: false,
  error: null,
  setAuth: (user, token) => set({ user, token, error: null }),
  clear: () => set({ user: null, token: null })
}));

export function useAuth() {
  const navigate = useNavigate();
  const { user, token, setAuth, clear, isLoading, error } = useAuthStore();

  const login = useCallback(
    async ({ username, password, remember }: LoginPayload) => {
      try {
        useAuthStore.setState({ isLoading: true, error: null });
        const { data } = await api.post("/auth/login", {
          username,
          password,
          remember_me: remember
        });
        setAuth({ username, role: "admin" }, data.access_token);
        api.defaults.headers.common.Authorization = `Bearer ${data.access_token}`;
        if (remember) {
          localStorage.setItem("gsp/token", data.refresh_token);
        }
        navigate("/");
      } catch (err) {
        useAuthStore.setState({ error: "Identifiants invalides" });
      } finally {
        useAuthStore.setState({ isLoading: false });
      }
    },
    [navigate, setAuth]
  );

  const logout = useCallback(() => {
    clear();
    localStorage.removeItem("gsp/token");
    navigate("/login");
  }, [clear, navigate]);

  return { user, token, login, logout, isLoading, error };
}

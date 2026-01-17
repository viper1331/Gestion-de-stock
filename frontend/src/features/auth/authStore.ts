import { createWithEqualityFn } from "zustand/traditional";
import { shallow } from "zustand/shallow";

export interface UserProfile {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  site_key: string;
  status: "active" | "pending" | "rejected" | "disabled";
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

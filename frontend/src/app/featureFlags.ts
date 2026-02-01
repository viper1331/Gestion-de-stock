import { createWithEqualityFn } from "zustand/traditional";
import { shallow } from "zustand/shallow";

import { fetchFeatureFlags } from "../api/featureFlags";

interface FeatureFlagsState {
  featureAriEnabled: boolean;
  isLoading: boolean;
  isLoaded: boolean;
  error: string | null;
  loadFeatureFlags: () => Promise<void>;
  setFeatureAriEnabled: (enabled: boolean) => void;
  reset: () => void;
}

const DEFAULT_STATE = {
  featureAriEnabled: false,
  isLoading: false,
  isLoaded: false,
  error: null
};

export const useFeatureFlagsStore = createWithEqualityFn<FeatureFlagsState>()(
  (set) => ({
    ...DEFAULT_STATE,
    loadFeatureFlags: async () => {
      set({ isLoading: true, error: null });
      try {
        const data = await fetchFeatureFlags();
        set({
          featureAriEnabled: data.feature_ari_enabled,
          isLoading: false,
          isLoaded: true,
          error: null
        });
      } catch {
        set({
          isLoading: false,
          isLoaded: true,
          error: "Impossible de charger les modules."
        });
      }
    },
    setFeatureAriEnabled: (enabled) =>
      set({ featureAriEnabled: enabled, isLoaded: true, error: null }),
    reset: () => set(DEFAULT_STATE)
  }),
  shallow
);

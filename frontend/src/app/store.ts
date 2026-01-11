import { createWithEqualityFn } from "zustand/traditional";
import { shallow } from "zustand/shallow";

interface UiState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const useUiStore = createWithEqualityFn<UiState>()(
  (set) => ({
    sidebarOpen: true,
    toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen }))
  }),
  shallow
);

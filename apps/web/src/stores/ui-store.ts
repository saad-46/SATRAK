import { create } from "zustand";

/**
 * Example UI-state store (client-only, ephemeral). Server data must never live
 * here — that is TanStack Query's responsibility. Feature modules add their own
 * small stores rather than growing one global store.
 */
interface UiState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebar: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebar: (open) => set({ sidebarOpen: open }),
}));

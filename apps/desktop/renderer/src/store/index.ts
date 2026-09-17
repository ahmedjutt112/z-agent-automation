/**
 * Global Zustand store — master prompt §4.
 * Holds app-wide state: current view, running tasks, mock mode, etc.
 */

import { create } from "zustand";

export type ViewId =
  | "dashboard"
  | "ai-agent"
  | "tasks"
  | "workflows"
  | "recorder"
  | "browser"
  | "files"
  | "schedules"
  | "history"
  | "logs"
  | "ai-models"
  | "integrations"
  | "permissions"
  | "settings";

interface AppState {
  view: ViewId;
  mockMode: boolean;
  emergencyEngaged: boolean;
  commandPaletteOpen: boolean;
  setView: (v: ViewId) => void;
  setMockMode: (m: boolean) => void;
  engageEmergency: () => void;
  resetEmergency: () => void;
  toggleCommandPalette: () => void;
}

export const useStore = create<AppState>((set) => ({
  view: "dashboard",
  mockMode: true,
  emergencyEngaged: false,
  commandPaletteOpen: false,
  setView: (view) => set({ view }),
  setMockMode: (mockMode) => set({ mockMode }),
  engageEmergency: () => set({ emergencyEngaged: true }),
  resetEmergency: () => set({ emergencyEngaged: false }),
  toggleCommandPalette: () =>
    set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
}));

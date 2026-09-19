/**
 * Global Zustand store — master prompt section 4.
 * Holds app-wide state: current view, running tasks, mock mode, theme,
 * developer mode, active profile id, etc.
 *
 * Theme + developer mode + active profile id are persisted to localStorage
 * (section 68 / 72 / 73 / 49). The store reads them on first access so any
 * component can subscribe without prop-drilling.
 */
import { create } from "zustand";
import { getTheme, setTheme as persistTheme, applyTheme, watchSystemTheme, } from "../lib/theme";
const DEV_MODE_KEY = "zai.developer_mode.v1";
const ACTIVE_PROFILE_KEY = "zai.active_profile_id.v1";
function readBool(key, fallback = false) {
    if (typeof window === "undefined")
        return fallback;
    try {
        const raw = window.localStorage.getItem(key);
        if (raw === null)
            return fallback;
        return raw === "true";
    }
    catch {
        return fallback;
    }
}
function readString(key, fallback = null) {
    if (typeof window === "undefined")
        return fallback;
    try {
        return window.localStorage.getItem(key);
    }
    catch {
        return fallback;
    }
}
function writeBool(key, value) {
    if (typeof window === "undefined")
        return;
    try {
        window.localStorage.setItem(key, String(value));
    }
    catch {
        /* ignore */
    }
}
function writeString(key, value) {
    if (typeof window === "undefined")
        return;
    try {
        if (value === null) {
            window.localStorage.removeItem(key);
        }
        else {
            window.localStorage.setItem(key, value);
        }
    }
    catch {
        /* ignore */
    }
}
export const useStore = create((set, get) => ({
    view: "dashboard",
    mockMode: true,
    emergencyEngaged: false,
    commandPaletteOpen: false,
    theme: getTheme(),
    setTheme: (config) => {
        persistTheme(config);
        set({ theme: config });
    },
    developerMode: readBool(DEV_MODE_KEY, false),
    setDeveloperMode: (enabled) => {
        writeBool(DEV_MODE_KEY, enabled);
        set({ developerMode: enabled });
    },
    toggleDeveloperMode: () => {
        const next = !get().developerMode;
        writeBool(DEV_MODE_KEY, next);
        set({ developerMode: next });
    },
    activeProfileId: readString(ACTIVE_PROFILE_KEY, null),
    setActiveProfileId: (id) => {
        writeString(ACTIVE_PROFILE_KEY, id);
        set({ activeProfileId: id });
    },
    setView: (view) => set({ view }),
    setMockMode: (mockMode) => set({ mockMode }),
    engageEmergency: () => set({ emergencyEngaged: true }),
    resetEmergency: () => set({ emergencyEngaged: false }),
    toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
}));
// ---------------------------------------------------------------------------
// Boot — apply the persisted theme + watch the system theme (section 68).
// Runs exactly once at module load. Safe in SSR (window-checks inside).
// ---------------------------------------------------------------------------
if (typeof window !== "undefined") {
    const initial = getTheme();
    applyTheme(initial);
    watchSystemTheme(() => {
        // The watch helper already re-applies when theme='system'; we just
        // re-read into the store so subscribers see the change.
        useStore.setState({ theme: getTheme() });
    });
}

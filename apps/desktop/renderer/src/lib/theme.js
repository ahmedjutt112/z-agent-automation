/**
 * Theme manager — master prompt section 68.
 *
 * ThemeConfig is persisted to localStorage and re-applied on app boot.
 * A 'theme-change' CustomEvent is dispatched on every setTheme() so any
 * React component can subscribe without prop-drilling.
 *
 * Master prompt section 73 (developer mode): the theme is what toggles the
 * DevPanel visible/hidden via the developer_mode flag in the Zustand store
 * (which itself is persisted via the same localStorage mechanism).
 */
const STORAGE_KEY = "zai.theme.v1";
const DEFAULT_THEME = {
    theme: "dark",
    accent: "blue",
    reduced_motion: false,
    high_contrast: false,
    font_scale: 1.0,
};
/** Map of accent -> hex color (master prompt section 68 — palette). */
const ACCENT_HEX = {
    blue: "#3b82f6",
    purple: "#a855f7",
    green: "#10b981",
    orange: "#f97316",
    pink: "#ec4899",
    red: "#ef4444",
};
const VALID_THEMES = ["dark", "light", "system"];
const VALID_ACCENTS = [
    "blue",
    "purple",
    "green",
    "orange",
    "pink",
    "red",
];
// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
export function getSystemTheme() {
    if (typeof window === "undefined")
        return "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
}
export function getAccentColorHex(accent) {
    return ACCENT_HEX[accent] ?? ACCENT_HEX.blue;
}
export function getTheme() {
    if (typeof window === "undefined")
        return { ...DEFAULT_THEME };
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (!raw)
            return { ...DEFAULT_THEME };
        const parsed = JSON.parse(raw);
        return {
            theme: VALID_THEMES.includes(parsed.theme)
                ? parsed.theme
                : DEFAULT_THEME.theme,
            accent: VALID_ACCENTS.includes(parsed.accent)
                ? parsed.accent
                : DEFAULT_THEME.accent,
            reduced_motion: parsed.reduced_motion ?? DEFAULT_THEME.reduced_motion,
            high_contrast: parsed.high_contrast ?? DEFAULT_THEME.high_contrast,
            font_scale: typeof parsed.font_scale === "number" &&
                parsed.font_scale >= 0.75 &&
                parsed.font_scale <= 1.5
                ? parsed.font_scale
                : DEFAULT_THEME.font_scale,
        };
    }
    catch {
        return { ...DEFAULT_THEME };
    }
}
export function setTheme(config) {
    if (typeof window === "undefined")
        return;
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    }
    catch {
        // localStorage may be unavailable in private mode — fall through silently.
    }
    applyTheme(config);
    window.dispatchEvent(new CustomEvent("theme-change", { detail: config }));
}
export function applyTheme(config) {
    if (typeof document === "undefined")
        return;
    const root = document.documentElement;
    const effective = config.theme === "system" ? getSystemTheme() : config.theme;
    // Theme class on <html> — lets Tailwind / CSS pick dark-mode rules.
    root.classList.toggle("dark", effective === "dark");
    root.classList.toggle("light", effective === "light");
    root.setAttribute("data-theme", effective);
    root.setAttribute("data-accent", config.accent);
    // CSS variables — section 68 mandates accent + reduced motion + high
    // contrast + font scale all be exposed to CSS.
    root.style.setProperty("--zai-accent", getAccentColorHex(config.accent));
    root.style.setProperty("--zai-font-scale", String(config.font_scale));
    if (config.reduced_motion) {
        root.setAttribute("data-reduced-motion", "true");
        root.style.setProperty("--zai-motion", "none");
    }
    else {
        root.removeAttribute("data-reduced-motion");
        root.style.setProperty("--zai-motion", "normal");
    }
    if (config.high_contrast) {
        root.setAttribute("data-high-contrast", "true");
        root.style.setProperty("--zai-contrast", "high");
    }
    else {
        root.removeAttribute("data-high-contrast");
        root.style.setProperty("--zai-contrast", "normal");
    }
    // Apply font-scale to the base font-size so all rem units scale together.
    root.style.fontSize = `${Math.round(16 * config.font_scale)}px`;
}
/**
 * Subscribe to system prefers-color-scheme changes. When the user has
 * selected theme='system', re-apply the effective theme on every change.
 * Returns an unsubscribe function.
 */
export function watchSystemTheme(onChange) {
    if (typeof window === "undefined" || !window.matchMedia) {
        return () => { };
    }
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
        const current = getTheme();
        if (current.theme === "system") {
            applyTheme(current);
        }
        onChange?.();
    };
    // addEventListener is the modern API; addListener is the Safari < 14 fallback.
    const mqAny = mq;
    if (mqAny.addEventListener) {
        mqAny.addEventListener("change", handler);
        return () => mqAny.removeEventListener?.("change", handler);
    }
    if (mqAny.addListener) {
        mqAny.addListener(handler);
        return () => mqAny.removeListener?.(handler);
    }
    return () => { };
}
export const DEFAULT_THEME_CONFIG = { ...DEFAULT_THEME };

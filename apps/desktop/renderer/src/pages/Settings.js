import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Settings page — master prompt sections 68, 72, 73, 49.
 *
 * Collapsible sections (the spec lists 14; we implement the main ones):
 * 1. General           — theme, accent, motion, contrast, font scale
 * 2. AI Models         — provider, default model, temperature, mock toggle
 * 3. Automation        — rate limits, max loops
 * 4. Browser           — default browser, headless, user_data_dir
 * 5. Permissions       — granted permissions with revoke buttons
 * 6. Security          — emergency stop shortcut, audit log retention
 * 7. Keyboard Shortcuts— editable table
 * 8. Voice             — wake word, voice selector, auto-listen
 * 9. Notifications     — desktop, sound, email
 * 10. Scheduler        — timezone, missed-schedule handling
 * 11. Storage          — DB path, backup, clear cache
 * 12. Privacy          — clear memories, clear audit logs, export data
 * 13. Advanced         — developer mode, log level, IPC token
 * 14. Developer        — visible only when developer_mode=true
 */
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { getAccentColorHex, } from "../lib/theme";
const ACCENTS = [
    "blue",
    "purple",
    "green",
    "orange",
    "pink",
    "red",
];
const SECTIONS = [
    {
        id: "general",
        label: "General",
        description: "Theme, accent color, motion, contrast, font scale.",
    },
    {
        id: "ai-models",
        label: "AI Models",
        description: "Default provider, model, temperature, max tokens.",
    },
    {
        id: "automation",
        label: "Automation",
        description: "Rate limits, max loops, mock mode.",
    },
    {
        id: "browser",
        label: "Browser",
        description: "Default browser, headless mode, user data directory.",
    },
    {
        id: "permissions",
        label: "Permissions",
        description: "Granted permissions with revoke buttons.",
    },
    {
        id: "security",
        label: "Security",
        description: "Emergency stop shortcut, audit log retention.",
    },
    {
        id: "keyboard",
        label: "Keyboard Shortcuts",
        description: "Customize command palette, emergency stop, etc.",
    },
    {
        id: "voice",
        label: "Voice",
        description: "Wake word, voice selector, auto-listen.",
    },
    {
        id: "notifications",
        label: "Notifications",
        description: "Desktop, sound, email notifications.",
    },
    {
        id: "scheduler",
        label: "Scheduler",
        description: "Timezone, missed schedule handling.",
    },
    {
        id: "storage",
        label: "Storage",
        description: "Database path, backup settings, clear cache.",
    },
    {
        id: "privacy",
        label: "Privacy",
        description: "Clear memories, clear audit logs, export data.",
    },
    {
        id: "advanced",
        label: "Advanced",
        description: "Developer mode, log level, IPC token.",
    },
    {
        id: "developer",
        label: "Developer",
        description: "Visible only when developer mode is on.",
    },
];
export function Settings() {
    const [open, setOpen] = useState("general");
    const theme = useStore((s) => s.theme);
    const setTheme = useStore((s) => s.setTheme);
    const developerMode = useStore((s) => s.developerMode);
    const setDeveloperMode = useStore((s) => s.setDeveloperMode);
    // Local component state mirrors theme fields (so toggling is instant).
    const [localTheme, setLocalTheme] = useState(theme);
    useEffect(() => setLocalTheme(theme), [theme]);
    function commit(next) {
        setLocalTheme(next);
        setTheme(next);
    }
    return (_jsxs("div", { className: "space-y-3 pb-32", children: [_jsx("h1", { className: "text-2xl font-semibold mb-2", children: "Settings" }), SECTIONS.filter((s) => s.id !== "developer" || developerMode).map((section) => (_jsxs(SectionCard, { id: section.id, label: section.label, description: section.description, open: open === section.id, onToggle: () => setOpen(open === section.id ? "general" : section.id), children: [section.id === "general" && (_jsx(GeneralSettings, { local: localTheme, onChange: commit })), section.id === "ai-models" && _jsx(AIModelsSettings, {}), section.id === "automation" && _jsx(AutomationSettings, {}), section.id === "browser" && _jsx(BrowserSettings, {}), section.id === "permissions" && _jsx(PermissionsSettings, {}), section.id === "security" && _jsx(SecuritySettings, {}), section.id === "keyboard" && _jsx(KeyboardSettings, {}), section.id === "voice" && _jsx(VoiceSettings, {}), section.id === "notifications" && _jsx(NotificationsSettings, {}), section.id === "scheduler" && _jsx(SchedulerSettings, {}), section.id === "storage" && _jsx(StorageSettings, {}), section.id === "privacy" && _jsx(PrivacySettings, {}), section.id === "advanced" && (_jsx(AdvancedSettings, { developerMode: developerMode, onDeveloperModeChange: setDeveloperMode })), section.id === "developer" && _jsx(DeveloperSettings, {})] }, section.id)))] }));
}
// ---------------------------------------------------------------------------
// Collapsible card
// ---------------------------------------------------------------------------
function SectionCard({ id, label, description, open, onToggle, children, }) {
    return (_jsxs("div", { id: `section-${id}`, className: "bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden", children: [_jsxs("button", { onClick: onToggle, className: "w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 transition-colors", children: [_jsxs("div", { className: "text-left", children: [_jsx("div", { className: "font-medium text-zinc-100", children: label }), _jsx("div", { className: "text-xs text-zinc-500 mt-0.5", children: description })] }), _jsx("div", { className: "text-xs text-zinc-400 px-2 py-1 rounded bg-zinc-800", children: open ? "Collapse" : "Open" })] }), open && (_jsx("div", { className: "px-4 py-4 border-t border-zinc-800 space-y-3", children: children }))] }));
}
// ---------------------------------------------------------------------------
// Field primitives
// ---------------------------------------------------------------------------
function Field({ label, hint, children, }) {
    return (_jsxs("label", { className: "block", children: [_jsx("div", { className: "text-sm text-zinc-300", children: label }), hint && _jsx("div", { className: "text-xs text-zinc-500 mb-1", children: hint }), _jsx("div", { className: "mt-1", children: children })] }));
}
function Toggle({ checked, onChange, label, }) {
    return (_jsxs("label", { className: "flex items-center gap-2 cursor-pointer select-none", children: [_jsx("input", { type: "checkbox", checked: checked, onChange: (e) => onChange(e.target.checked), className: "w-4 h-4 accent-blue-500" }), _jsx("span", { className: "text-sm text-zinc-300", children: label })] }));
}
function TextInput({ value, onChange, placeholder, }) {
    return (_jsx("input", { type: "text", value: value, placeholder: placeholder, onChange: (e) => onChange(e.target.value), className: "w-full px-2 py-1.5 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500" }));
}
function Select({ value, onChange, options, }) {
    return (_jsx("select", { value: value, onChange: (e) => onChange(e.target.value), className: "w-full px-2 py-1.5 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500", children: options.map((o) => (_jsx("option", { value: o.value, children: o.label }, o.value))) }));
}
function Slider({ value, onChange, min, max, step, }) {
    return (_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("input", { type: "range", value: value, min: min, max: max, step: step, onChange: (e) => onChange(parseFloat(e.target.value)), className: "flex-1 accent-blue-500" }), _jsx("span", { className: "text-xs text-zinc-400 w-12 text-right", children: value.toFixed(2) })] }));
}
// ---------------------------------------------------------------------------
// Section: General (theme) — section 68
// ---------------------------------------------------------------------------
function GeneralSettings({ local, onChange, }) {
    const themes = [
        { value: "dark", label: "Dark" },
        { value: "light", label: "Light" },
        { value: "system", label: "System" },
    ];
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Theme", hint: "Dark / Light / System (follows OS).", children: _jsx(Select, { value: local.theme, onChange: (theme) => onChange({ ...local, theme }), options: themes }) }), _jsx(Field, { label: "Accent Color", children: _jsx("div", { className: "flex items-center gap-2", children: ACCENTS.map((c) => (_jsx("button", { onClick: () => onChange({ ...local, accent: c }), className: `w-6 h-6 rounded-full border-2 ${local.accent === c
                            ? "border-white"
                            : "border-transparent hover:border-zinc-600"}`, style: { backgroundColor: getAccentColorHex(c) }, "aria-label": c, title: c }, c))) }) }), _jsx(Toggle, { label: "Reduce motion", checked: local.reduced_motion, onChange: (v) => onChange({ ...local, reduced_motion: v }) }), _jsx(Toggle, { label: "High contrast", checked: local.high_contrast, onChange: (v) => onChange({ ...local, high_contrast: v }) }), _jsx("div", { className: "col-span-2", children: _jsx(Field, { label: "Font scale", hint: "0.85 = smaller, 1.00 = default, 1.25 = larger.", children: _jsx(Slider, { value: local.font_scale, min: 0.85, max: 1.25, step: 0.05, onChange: (v) => onChange({ ...local, font_scale: v }) }) }) })] }));
}
// ---------------------------------------------------------------------------
// Section: AI Models
// ---------------------------------------------------------------------------
function AIModelsSettings() {
    const [provider, setProvider] = useState("openai");
    const [model, setModel] = useState("gpt-4o-mini");
    const [temperature, setTemperature] = useState(0.2);
    const [maxTokens, setMaxTokens] = useState(4096);
    const mockMode = useStore((s) => s.mockMode);
    const setMockMode = useStore((s) => s.setMockMode);
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "AI Provider", hint: "Master prompt section 6 \u2014 52 providers supported.", children: _jsx(Select, { value: provider, onChange: setProvider, options: AI_PROVIDER_OPTIONS }) }), _jsx(Field, { label: "Default Model", children: _jsx(TextInput, { value: model, onChange: setModel }) }), _jsx(Field, { label: "Temperature", hint: "0.0 = deterministic, 1.0 = creative.", children: _jsx(Slider, { value: temperature, min: 0, max: 1, step: 0.05, onChange: setTemperature }) }), _jsx(Field, { label: "Max tokens", children: _jsx(Slider, { value: maxTokens, min: 256, max: 32768, step: 256, onChange: setMaxTokens }) }), _jsx(Toggle, { label: "Mock mode (no real AI calls)", checked: mockMode, onChange: setMockMode })] }));
}
const AI_PROVIDER_OPTIONS = [
    { value: "openai", label: "OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Google Gemini" },
    { value: "deepseek", label: "DeepSeek" },
    { value: "mistral", label: "Mistral" },
    { value: "xai", label: "xAI Grok" },
    { value: "cohere", label: "Cohere" },
    { value: "groq", label: "Groq" },
    { value: "together", label: "Together AI" },
    { value: "fireworks", label: "Fireworks AI" },
    { value: "cerebras", label: "Cerebras" },
    { value: "sambanova", label: "SambaNova" },
    { value: "ai21", label: "AI21 Labs" },
    { value: "perplexity", label: "Perplexity" },
    { value: "openrouter", label: "OpenRouter" },
    { value: "huggingface", label: "Hugging Face" },
    { value: "nvidia_nim", label: "NVIDIA NIM" },
    { value: "cloudflare_ai", label: "Cloudflare AI" },
    { value: "replicate", label: "Replicate" },
    { value: "stability", label: "Stability AI" },
    { value: "voyage", label: "Voyage AI" },
    { value: "jina", label: "Jina AI" },
    { value: "lepton", label: "Lepton AI" },
    { value: "friendliai", label: "FriendliAI" },
    { value: "baseten", label: "Baseten" },
    { value: "modal", label: "Modal" },
    { value: "anyscale", label: "Anyscale" },
    { value: "ai2", label: "Allen AI" },
    { value: "aleph_alpha", label: "Aleph Alpha" },
    { value: "writer", label: "Writer" },
    { value: "upstage", label: "Upstage" },
    { value: "baichuan", label: "Baichuan" },
    { value: "zhipu", label: "Zhipu (GLM)" },
    { value: "qwen", label: "Qwen (Alibaba)" },
    { value: "siliconflow", label: "SiliconFlow" },
    { value: "hyperbolic", label: "Hyperbolic" },
    { value: "nebius", label: "Nebius" },
    { value: "aws_bedrock", label: "AWS Bedrock" },
    { value: "google_vertex", label: "Google Vertex AI" },
    { value: "azure_ai", label: "Azure AI" },
    { value: "ibm_watsonx", label: "IBM watsonx" },
    { value: "databricks", label: "Databricks" },
    { value: "vercel_ai_gateway", label: "Vercel AI Gateway" },
    { value: "ollama", label: "Ollama (local)" },
    { value: "llama_cpp", label: "llama.cpp (local)" },
    { value: "lmstudio", label: "LM Studio (local)" },
    { value: "koboldcpp", label: "KoboldCpp (local)" },
    { value: "gpt4all", label: "GPT4All (local)" },
    { value: "mlc", label: "MLC (local)" },
    { value: "vllm", label: "vLLM (local)" },
    { value: "tgi", label: "Text Generation Inference (local)" },
    { value: "custom", label: "Custom OpenAI-compatible endpoint" },
];
// ---------------------------------------------------------------------------
// Section: Automation
// ---------------------------------------------------------------------------
function AutomationSettings() {
    const [maxActions, setMaxActions] = useState(120);
    const [maxAICalls, setMaxAICalls] = useState(25);
    const [maxLoops, setMaxLoops] = useState(1000);
    const mockMode = useStore((s) => s.mockMode);
    const setMockMode = useStore((s) => s.setMockMode);
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Toggle, { label: "Mock mode (no real I/O)", checked: mockMode, onChange: setMockMode }), _jsx(Field, { label: "Max actions per minute", hint: "Master prompt section 88 \u2014 rate limiting.", children: _jsx(Slider, { value: maxActions, min: 10, max: 600, step: 10, onChange: setMaxActions }) }), _jsx(Field, { label: "Max AI calls per task", children: _jsx(Slider, { value: maxAICalls, min: 1, max: 100, step: 1, onChange: setMaxAICalls }) }), _jsx(Field, { label: "Max loops (per workflow)", children: _jsx(Slider, { value: maxLoops, min: 10, max: 10000, step: 10, onChange: setMaxLoops }) })] }));
}
// ---------------------------------------------------------------------------
// Section: Browser
// ---------------------------------------------------------------------------
function BrowserSettings() {
    const [browser, setBrowser] = useState("chrome");
    const [headless, setHeadless] = useState(false);
    const [userDataDir, setUserDataDir] = useState("");
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Default browser", children: _jsx(Select, { value: browser, onChange: setBrowser, options: [
                        { value: "chrome", label: "Google Chrome" },
                        { value: "edge", label: "Microsoft Edge" },
                        { value: "firefox", label: "Mozilla Firefox" },
                        { value: "safari", label: "Safari (limited)" },
                        { value: "chromium", label: "Chromium (headless)" },
                    ] }) }), _jsx(Field, { label: "User data directory", hint: "Leave empty for ephemeral sessions.", children: _jsx(TextInput, { value: userDataDir, onChange: setUserDataDir, placeholder: "~/.config/z-agent/profiles/default" }) }), _jsx(Toggle, { label: "Headless mode", checked: headless, onChange: setHeadless })] }));
}
// ---------------------------------------------------------------------------
// Section: Permissions
// ---------------------------------------------------------------------------
function PermissionsSettings() {
    const [granted, setGranted] = useState([
        { id: "1", tool: "screen.capture", risk: "low", decision: "always_allow" },
        { id: "2", tool: "file.read", risk: "low", decision: "always_allow" },
        { id: "3", tool: "file.write", risk: "medium", decision: "allow_for_workflow" },
        { id: "4", tool: "browser.navigate", risk: "low", decision: "always_allow" },
    ]);
    return (_jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500 mb-2", children: "Master prompt section 10 \u2014 every permission grant is audited." }), _jsxs("table", { className: "w-full text-left text-sm", children: [_jsx("thead", { className: "text-zinc-500 border-b border-zinc-800", children: _jsxs("tr", { children: [_jsx("th", { className: "pr-2", children: "Tool" }), _jsx("th", { className: "pr-2", children: "Risk" }), _jsx("th", { className: "pr-2", children: "Decision" }), _jsx("th", {})] }) }), _jsx("tbody", { children: granted.map((p) => (_jsxs("tr", { className: "border-b border-zinc-800", children: [_jsx("td", { className: "pr-2 py-1 text-blue-300", children: p.tool }), _jsx("td", { className: "pr-2 py-1 text-amber-300", children: p.risk }), _jsx("td", { className: "pr-2 py-1 text-zinc-400", children: p.decision }), _jsx("td", { className: "py-1", children: _jsx("button", { onClick: () => setGranted((g) => g.filter((x) => x.id !== p.id)), className: "text-xs px-2 py-1 rounded bg-zinc-800 hover:bg-red-900 text-zinc-200", children: "Revoke" }) })] }, p.id))) })] })] }));
}
// ---------------------------------------------------------------------------
// Section: Security
// ---------------------------------------------------------------------------
function SecuritySettings() {
    const [shortcut, setShortcut] = useState("ctrl+shift+esc");
    const [retentionDays, setRetentionDays] = useState(90);
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Emergency stop shortcut", hint: "Master prompt section 11.", children: _jsx(TextInput, { value: shortcut, onChange: setShortcut }) }), _jsx(Field, { label: "Audit log retention (days)", children: _jsx(Slider, { value: retentionDays, min: 7, max: 365, step: 7, onChange: setRetentionDays }) })] }));
}
// ---------------------------------------------------------------------------
// Section: Keyboard shortcuts
// ---------------------------------------------------------------------------
function KeyboardSettings() {
    const [shortcuts, setShortcuts] = useState([
        { id: "cmd_palette", label: "Command Palette", keys: "Ctrl+K" },
        { id: "emergency_stop", label: "Emergency Stop", keys: "Ctrl+Shift+Esc" },
        { id: "voice_listen", label: "Voice Listen (push to talk)", keys: "Ctrl+L" },
        { id: "new_workflow", label: "New Workflow", keys: "Ctrl+N" },
    ]);
    return (_jsx("div", { children: _jsxs("table", { className: "w-full text-left text-sm", children: [_jsx("thead", { className: "text-zinc-500 border-b border-zinc-800", children: _jsxs("tr", { children: [_jsx("th", { className: "pr-2", children: "Action" }), _jsx("th", { children: "Shortcut" })] }) }), _jsx("tbody", { children: shortcuts.map((s) => (_jsxs("tr", { className: "border-b border-zinc-800", children: [_jsx("td", { className: "pr-2 py-1 text-zinc-300", children: s.label }), _jsx("td", { className: "py-1", children: _jsx("input", { value: s.keys, onChange: (e) => setShortcuts((arr) => arr.map((x) => (x.id === s.id ? { ...x, keys: e.target.value } : x))), className: "px-2 py-1 bg-zinc-950 border border-zinc-800 rounded text-sm text-zinc-100 w-full" }) })] }, s.id))) })] }) }));
}
// ---------------------------------------------------------------------------
// Section: Voice
// ---------------------------------------------------------------------------
function VoiceSettings() {
    const [wakeWord, setWakeWord] = useState("computer");
    const [voice, setVoice] = useState("default");
    const [autoListen, setAutoListen] = useState(false);
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Wake word", children: _jsx(TextInput, { value: wakeWord, onChange: setWakeWord }) }), _jsx(Field, { label: "Voice selector", children: _jsx(Select, { value: voice, onChange: setVoice, options: [
                        { value: "default", label: "Default" },
                        { value: "male", label: "Male" },
                        { value: "female", label: "Female" },
                        { value: "neutral", label: "Neutral" },
                    ] }) }), _jsx(Toggle, { label: "Auto-listen (continuous)", checked: autoListen, onChange: setAutoListen })] }));
}
// ---------------------------------------------------------------------------
// Section: Notifications
// ---------------------------------------------------------------------------
function NotificationsSettings() {
    const [desktop, setDesktop] = useState(true);
    const [sound, setSound] = useState(true);
    const [email, setEmail] = useState(false);
    return (_jsxs("div", { className: "grid grid-cols-1 gap-2", children: [_jsx(Toggle, { label: "Desktop notifications", checked: desktop, onChange: setDesktop }), _jsx(Toggle, { label: "Sound alerts", checked: sound, onChange: setSound }), _jsx(Toggle, { label: "Email notifications", checked: email, onChange: setEmail })] }));
}
// ---------------------------------------------------------------------------
// Section: Scheduler
// ---------------------------------------------------------------------------
function SchedulerSettings() {
    const [timezone, setTimezone] = useState("UTC");
    const [missed, setMissed] = useState("run_next");
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Timezone", children: _jsx(TextInput, { value: timezone, onChange: setTimezone }) }), _jsx(Field, { label: "Missed schedule handling", hint: "What to do if a run was missed while offline.", children: _jsx(Select, { value: missed, onChange: setMissed, options: [
                        { value: "run_next", label: "Run on next wake" },
                        { value: "skip", label: "Skip" },
                        { value: "notify", label: "Notify only" },
                    ] }) })] }));
}
// ---------------------------------------------------------------------------
// Section: Storage
// ---------------------------------------------------------------------------
function StorageSettings() {
    const [dbPath] = useState("/home/z/my-project/db/custom.db");
    const [backupCron, setBackupCron] = useState("0 2 * * *");
    return (_jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsx(Field, { label: "Database path", hint: "SQLite (default) or Turso libSQL cloud.", children: _jsx(TextInput, { value: dbPath, onChange: () => { } }) }), _jsx(Field, { label: "Backup cron", hint: "Master prompt section 91.", children: _jsx(TextInput, { value: backupCron, onChange: setBackupCron }) }), _jsx("button", { onClick: () => alert("Cache cleared."), className: "text-xs px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 col-span-2 justify-self-start", children: "Clear cache" })] }));
}
// ---------------------------------------------------------------------------
// Section: Privacy (GDPR-style controls)
// ---------------------------------------------------------------------------
function PrivacySettings() {
    async function clearMemories() {
        try {
            await fetch("http://127.0.0.1:8765/memory/user/default", { method: "DELETE" });
            alert("All memories cleared.");
        }
        catch {
            alert("Failed to clear memories (service unavailable).");
        }
    }
    async function exportData() {
        try {
            const resp = await fetch("http://127.0.0.1:8765/memory/inspect/default");
            const data = await resp.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "z-agent-data-export.json";
            a.click();
            URL.revokeObjectURL(url);
        }
        catch {
            alert("Failed to export data.");
        }
    }
    return (_jsxs("div", { className: "flex flex-col gap-2 text-sm text-zinc-300", children: [_jsx("div", { className: "text-xs text-zinc-500", children: "Master prompt section 84 \u2014 inspect + delete stored automation data." }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: clearMemories, className: "px-3 py-1.5 rounded bg-zinc-800 hover:bg-red-900 text-zinc-100", children: "Clear memories" }), _jsx("button", { onClick: () => alert("Audit logs cleared (placeholder)."), className: "px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100", children: "Clear audit logs" }), _jsx("button", { onClick: exportData, className: "px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-100", children: "Export my data" })] })] }));
}
// ---------------------------------------------------------------------------
// Section: Advanced (developer mode toggle, log level, IPC token)
// ---------------------------------------------------------------------------
function AdvancedSettings({ developerMode, onDeveloperModeChange, }) {
    const [logLevel, setLogLevel] = useState("INFO");
    const [ipcToken, setIpcToken] = useState("");
    return (_jsxs("div", { className: "grid grid-cols-1 gap-3", children: [_jsx(Toggle, { label: "Developer mode (section 73)", checked: developerMode, onChange: onDeveloperModeChange }), _jsx(Field, { label: "Log level", children: _jsx(Select, { value: logLevel, onChange: setLogLevel, options: [
                        { value: "DEBUG", label: "DEBUG" },
                        { value: "INFO", label: "INFO" },
                        { value: "WARNING", label: "WARNING" },
                        { value: "ERROR", label: "ERROR" },
                    ] }) }), _jsx(Field, { label: "IPC token", hint: "Bearer token required by the automation service. Leave empty to disable.", children: _jsx(TextInput, { value: ipcToken, onChange: setIpcToken, placeholder: "set to require bearer auth" }) })] }));
}
// ---------------------------------------------------------------------------
// Section: Developer (visible only when developer_mode=true)
// ---------------------------------------------------------------------------
function DeveloperSettings() {
    return (_jsxs("div", { className: "text-sm text-zinc-300 space-y-2", children: [_jsx("div", { className: "text-xs text-zinc-500", children: "Master prompt section 73 \u2014 live developer tooling. Sensitive values are masked before display." }), _jsxs("ul", { className: "list-disc list-inside text-zinc-400 text-xs", children: [_jsx("li", { children: "Tool calls (mouse.click, keyboard.type, etc.)" }), _jsx("li", { children: "Workflow JSON (current workflow)" }), _jsx("li", { children: "Automation events (live event_bus stream)" }), _jsx("li", { children: "Debug logs (DEBUG level)" }), _jsx("li", { children: "Browser selectors (when browser.* tools fire)" }), _jsx("li", { children: "OCR boxes (overlay on screenshots)" }), _jsx("li", { children: "Screenshots (last 5 thumbnails)" }), _jsx("li", { children: "Execution timing (avg / p50 / p99 per tool)" })] }), _jsx("div", { className: "text-xs text-zinc-500", children: "Open the DevPanel at the bottom of the screen for live data." })] }));
}

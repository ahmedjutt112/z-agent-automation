import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Sidebar — master prompt §30.
 * Modern dark workstation style (§29).
 */
import { useStore } from "../store";
const NAV_ITEMS = [
    { id: "dashboard", label: "Dashboard" },
    { id: "ai-agent", label: "AI Agent" },
    { id: "assistant", label: "AI Assistant" },
    { id: "tasks", label: "Tasks" },
    { id: "workflows", label: "Workflows" },
    { id: "marketplace", label: "Marketplace" },
    { id: "recorder", label: "Recorder" },
    { id: "browser", label: "Browser" },
    { id: "files", label: "Files" },
    { id: "schedules", label: "Schedules" },
    { id: "history", label: "History" },
    { id: "logs", label: "Logs" },
    { id: "teams", label: "Teams" },
    { id: "analytics", label: "Analytics" },
];
const SECONDARY_ITEMS = [
    { id: "ai-models", label: "AI Models" },
    { id: "integrations", label: "Integrations" },
    { id: "permissions", label: "Permissions" },
    { id: "voice-settings", label: "Voice" },
    { id: "settings", label: "Settings" },
];
export function Sidebar() {
    const view = useStore((s) => s.view);
    const setView = useStore((s) => s.setView);
    return (_jsxs("aside", { className: "w-60 flex-shrink-0 border-r border-zinc-800 bg-zinc-900 flex flex-col", children: [_jsxs("div", { className: "px-5 py-5 border-b border-zinc-800", children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: "Z-Agent" }), _jsx("div", { className: "text-sm font-medium mt-1", children: "Automation Platform" })] }), _jsxs("nav", { className: "flex-1 px-2 py-3 space-y-1 overflow-y-auto", children: [NAV_ITEMS.map((item) => (_jsx("button", { onClick: () => setView(item.id), className: `w-full text-left px-3 py-2 rounded text-sm transition-colors ${view === item.id
                            ? "bg-zinc-700 text-white"
                            : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"}`, children: item.label }, item.id))), _jsx("div", { className: "pt-4 pb-2 px-3 text-xs uppercase tracking-wider text-zinc-600", children: "Configure" }), SECONDARY_ITEMS.map((item) => (_jsx("button", { onClick: () => setView(item.id), className: `w-full text-left px-3 py-2 rounded text-sm transition-colors ${view === item.id
                            ? "bg-zinc-700 text-white"
                            : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"}`, children: item.label }, item.id)))] })] }));
}

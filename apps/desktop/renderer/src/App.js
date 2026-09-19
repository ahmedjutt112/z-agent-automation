import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Root App component — master prompt §29 (UI/UX), §30 (sidebar), §70 (command palette).
 */
import { useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { CommandPalette } from "./components/CommandPalette";
import { VoiceButton } from "./components/VoiceButton";
import { DevPanel } from "./components/DevPanel";
import { Dashboard } from "./pages/Dashboard";
import { AIAgent } from "./pages/AIAgent";
import { Assistant } from "./pages/Assistant";
import { Workflows } from "./pages/Workflows";
import { Marketplace } from "./pages/Marketplace";
import { Tasks } from "./pages/Tasks";
import { Logs } from "./pages/Logs";
import { Settings } from "./pages/Settings";
import { Integrations } from "./pages/Integrations";
import { VoiceSettings } from "./pages/VoiceSettings";
import { Recorder } from "./pages/Recorder";
import { Browser } from "./pages/Browser";
import { Files } from "./pages/Files";
import { Schedules } from "./pages/Schedules";
import { History } from "./pages/History";
import { AIModels } from "./pages/AIModels";
import { Permissions } from "./pages/Permissions";
import { Teams } from "./pages/Teams";
import { Analytics } from "./pages/Analytics";
import { EmergencyBanner } from "./components/EmergencyBanner";
import { useStore } from "./store";
export default function App() {
    const view = useStore((s) => s.view);
    const togglePalette = useStore((s) => s.toggleCommandPalette);
    const engage = useStore((s) => s.engageEmergency);
    // Command palette shortcut: Ctrl+K  (master prompt §70)
    useEffect(() => {
        const handler = (e) => {
            if (e.ctrl && e.key === "k") {
                e.preventDefault();
                togglePalette();
            }
            // Emergency stop shortcut: Ctrl+Shift+Esc (master prompt §11)
            if (e.ctrl && e.shift && e.key === "Escape") {
                e.preventDefault();
                engage();
                window.zai?.emergencyStop?.().catch(() => { });
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, [togglePalette, engage]);
    return (_jsxs("div", { className: "flex h-screen bg-zinc-950 text-zinc-100 font-sans", children: [_jsx(Sidebar, {}), _jsxs("main", { className: "flex-1 flex flex-col overflow-hidden", children: [_jsx(EmergencyBanner, {}), _jsx("div", { className: "flex-1 overflow-auto p-6", children: renderView(view) })] }), _jsx(CommandPalette, {}), _jsx(VoiceButton, {}), _jsx(DevPanel, {})] }));
}
function renderView(view) {
    switch (view) {
        case "dashboard": return _jsx(Dashboard, {});
        case "ai-agent": return _jsx(AIAgent, {});
        case "assistant": return _jsx(Assistant, {});
        case "workflows": return _jsx(Workflows, {});
        case "marketplace": return _jsx(Marketplace, {});
        case "tasks": return _jsx(Tasks, {});
        case "logs": return _jsx(Logs, {});
        case "integrations": return _jsx(Integrations, {});
        case "voice-settings": return _jsx(VoiceSettings, {});
        case "settings": return _jsx(Settings, {});
        case "recorder": return _jsx(Recorder, {});
        case "browser": return _jsx(Browser, {});
        case "files": return _jsx(Files, {});
        case "schedules": return _jsx(Schedules, {});
        case "history": return _jsx(History, {});
        case "ai-models": return _jsx(AIModels, {});
        case "permissions": return _jsx(Permissions, {});
        case "teams": return _jsx(Teams, {});
        case "analytics": return _jsx(Analytics, {});
        default: return _jsx(Dashboard, {});
    }
}

/**
 * Root App component — master prompt §29 (UI/UX), §30 (sidebar), §70 (command palette).
 */

import React, { useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { CommandPalette } from "./components/CommandPalette";
import { Dashboard } from "./pages/Dashboard";
import { AIAgent } from "./pages/AIAgent";
import { Workflows } from "./pages/Workflows";
import { Tasks } from "./pages/Tasks";
import { Logs } from "./pages/Logs";
import { Settings } from "./pages/Settings";
import { EmergencyBanner } from "./components/EmergencyBanner";
import { useStore } from "./store";

export default function App() {
  const view = useStore((s) => s.view);
  const togglePalette = useStore((s) => s.toggleCommandPalette);
  const engage = useStore((s) => s.engageEmergency);

  // Command palette shortcut: Ctrl+K  (master prompt §70)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrl && e.key === "k") {
        e.preventDefault();
        togglePalette();
      }
      // Emergency stop shortcut: Ctrl+Shift+Esc (master prompt §11)
      if (e.ctrl && e.shift && e.key === "Escape") {
        e.preventDefault();
        engage();
        window.zai?.emergencyStop?.().catch(() => {});
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePalette, engage]);

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 font-sans">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <EmergencyBanner />
        <div className="flex-1 overflow-auto p-6">
          {renderView(view)}
        </div>
      </main>
      <CommandPalette />
    </div>
  );
}

function renderView(view: string): React.ReactNode {
  switch (view) {
    case "dashboard": return <Dashboard />;
    case "ai-agent": return <AIAgent />;
    case "workflows": return <Workflows />;
    case "tasks": return <Tasks />;
    case "logs": return <Logs />;
    case "settings": return <Settings />;
    default: return <Dashboard />;
  }
}

/**
 * Sidebar — master prompt §30.
 * Modern dark workstation style (§29).
 */

import { useStore, ViewId } from "../store";

const NAV_ITEMS: { id: ViewId; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "ai-agent", label: "AI Agent" },
  { id: "tasks", label: "Tasks" },
  { id: "workflows", label: "Workflows" },
  { id: "recorder", label: "Recorder" },
  { id: "browser", label: "Browser" },
  { id: "files", label: "Files" },
  { id: "schedules", label: "Schedules" },
  { id: "history", label: "History" },
  { id: "logs", label: "Logs" },
];

const SECONDARY_ITEMS: { id: ViewId; label: string }[] = [
  { id: "ai-models", label: "AI Models" },
  { id: "integrations", label: "Integrations" },
  { id: "permissions", label: "Permissions" },
  { id: "settings", label: "Settings" },
];

export function Sidebar() {
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);

  return (
    <aside className="w-60 flex-shrink-0 border-r border-zinc-800 bg-zinc-900 flex flex-col">
      <div className="px-5 py-5 border-b border-zinc-800">
        <div className="text-xs uppercase tracking-wider text-zinc-500">Z-Agent</div>
        <div className="text-sm font-medium mt-1">Automation Platform</div>
      </div>
      <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => setView(item.id)}
            className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
              view === item.id
                ? "bg-zinc-700 text-white"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            }`}
          >
            {item.label}
          </button>
        ))}
        <div className="pt-4 pb-2 px-3 text-xs uppercase tracking-wider text-zinc-600">Configure</div>
        {SECONDARY_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => setView(item.id)}
            className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
              view === item.id
                ? "bg-zinc-700 text-white"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

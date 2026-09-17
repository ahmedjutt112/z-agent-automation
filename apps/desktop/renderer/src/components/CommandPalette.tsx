/** Command palette — master prompt §70. Ctrl+K to open. */

import { useState } from "react";
import { useStore, ViewId } from "../store";

const COMMANDS: { id: ViewId; label: string; hint: string }[] = [
  { id: "dashboard", label: "Go to Dashboard", hint: "Dashboard" },
  { id: "ai-agent", label: "Open AI Agent chat", hint: "AI" },
  { id: "workflows", label: "Open Workflow Editor", hint: "Workflows" },
  { id: "tasks", label: "View Tasks", hint: "Tasks" },
  { id: "recorder", label: "Start Recording", hint: "Recorder" },
  { id: "settings", label: "Open Settings", hint: "Settings" },
  { id: "logs", label: "Open Logs", hint: "Logs" },
];

export function CommandPalette() {
  const open = useStore((s) => s.commandPaletteOpen);
  const toggle = useStore((s) => s.toggleCommandPalette);
  const setView = useStore((s) => s.setView);
  const [query, setQuery] = useState("");

  if (!open) return null;

  const filtered = COMMANDS.filter((c) =>
    c.label.toLowerCase().includes(query.toLowerCase()) ||
    c.hint.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-32"
      onClick={toggle}
    >
      <div
        className="w-full max-w-xl bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Type a command..."
          className="w-full px-4 py-3 bg-transparent text-zinc-100 placeholder-zinc-500 outline-none border-b border-zinc-800"
        />
        <ul className="max-h-80 overflow-y-auto">
          {filtered.map((cmd) => (
            <li key={cmd.id}>
              <button
                onClick={() => {
                  setView(cmd.id);
                  toggle();
                }}
                className="w-full text-left px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-800 hover:text-white"
              >
                {cmd.label}
                <span className="ml-2 text-xs text-zinc-600">{cmd.hint}</span>
              </button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="px-4 py-6 text-sm text-zinc-600 text-center">No matching commands</li>
          )}
        </ul>
      </div>
    </div>
  );
}

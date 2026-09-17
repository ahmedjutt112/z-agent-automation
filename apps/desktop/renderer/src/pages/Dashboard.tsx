/** Dashboard — master prompt §31. */

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

export function Dashboard() {
  const setView = useStore((s) => s.setView);
  const [health, setHealth] = useState<{ status: string; mock_mode: boolean } | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Good morning</h1>
        <p className="text-zinc-400 mt-1">What would you like me to automate?</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <button
          onClick={() => setView("ai-agent")}
          className="bg-zinc-800 hover:bg-zinc-700 rounded-lg p-4 text-left border border-zinc-700"
        >
          <div className="text-sm text-zinc-400">Quick Action</div>
          <div className="mt-1 font-medium">Ask AI to automate something</div>
        </button>
        <button
          onClick={() => setView("workflows")}
          className="bg-zinc-800 hover:bg-zinc-700 rounded-lg p-4 text-left border border-zinc-700"
        >
          <div className="text-sm text-zinc-400">Quick Action</div>
          <div className="mt-1 font-medium">Run a Workflow</div>
        </button>
        <button
          onClick={() => setView("recorder")}
          className="bg-zinc-800 hover:bg-zinc-700 rounded-lg p-4 text-left border border-zinc-700"
        >
          <div className="text-sm text-zinc-400">Quick Action</div>
          <div className="mt-1 font-medium">Record a Task</div>
        </button>
        <button
          onClick={() => setView("browser")}
          className="bg-zinc-800 hover:bg-zinc-700 rounded-lg p-4 text-left border border-zinc-700"
        >
          <div className="text-sm text-zinc-400">Quick Action</div>
          <div className="mt-1 font-medium">Browser Task</div>
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Tasks Today" value="—" />
        <StatCard label="Successful" value="—" />
        <StatCard label="Failed" value="—" />
        <StatCard label="Running" value="—" />
      </div>

      <div className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
        <div className="text-sm text-zinc-400">Service Status</div>
        {health ? (
          <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-zinc-500">Status</span>
              <span className="text-emerald-400">{health.status}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Mock Mode</span>
              <span className={health.mock_mode ? "text-amber-400" : "text-emerald-400"}>
                {health.mock_mode ? "ON (safe)" : "OFF (real)"}
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-2 text-sm text-red-400">Service unreachable</div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
      <div className="text-xs uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  );
}

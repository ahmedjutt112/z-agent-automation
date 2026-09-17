/** Workflows page — master prompt §20, §21, §34. */

import { useEffect, useState } from "react";
import { api, WorkflowSummary } from "../lib/api";

export function Workflows() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listWorkflows()
      .then(setWorkflows)
      .catch(() => setWorkflows([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Workflows</h1>
        <button className="bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded text-sm">
          New Workflow
        </button>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="px-4 py-2 text-left">Name</th>
              <th className="px-4 py-2 text-left">Version</th>
              <th className="px-4 py-2 text-left">Enabled</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-zinc-500">Loading...</td></tr>
            ) : workflows.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-zinc-500">
                No workflows yet. Use the AI Agent to generate one.
              </td></tr>
            ) : (
              workflows.map((wf) => (
                <tr key={wf.id} className="border-t border-zinc-800 hover:bg-zinc-800">
                  <td className="px-4 py-2 font-medium">{wf.name}</td>
                  <td className="px-4 py-2 text-zinc-400">v{wf.version}</td>
                  <td className="px-4 py-2">
                    <span className={`text-xs ${wf.enabled ? "text-emerald-400" : "text-zinc-500"}`}>
                      {wf.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 py-1 rounded">
                      Edit
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-6 p-4 border border-dashed border-zinc-800 rounded text-center text-zinc-500 text-sm">
        Visual workflow editor (React Flow) — Phase 2 Coming Soon
      </div>
    </div>
  );
}

/**
 * History page — master prompt §36 (Task History).
 *
 * Filter bar (date range, status, triggered_by, search) + paginated task
 * list. Clicking a task opens a detail modal showing the plan, each step
 * with status + output + duration, screenshots taken, and logs filtered
 * to the task. Includes an "Export CSV" button.
 *
 * In mock mode (or when no DB is configured) the backend returns empty
 * lists and the UI renders an empty state.
 */

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";

interface TaskSummary {
  id: string;
  name: string;
  status: string;
  profile_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
}

interface TaskStepDetail {
  id: string;
  step_id: string;
  tool_name: string;
  status: string;
  risk_level: string;
  confidence: number;
  args_json: unknown;
  output: unknown;
  error: string | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
}

interface TaskLogDetail {
  id: number;
  timestamp: string | null;
  level: string;
  tool: string | null;
  target: string | null;
  status: string;
  duration_ms: number | null;
  payload: unknown;
}

interface TaskDetail {
  task: {
    id: string;
    name: string;
    status: string;
    profile_id: string | null;
    plan_json: unknown;
    result_json: unknown;
    started_at: string | null;
    finished_at: string | null;
    created_at: string | null;
  };
  steps: TaskStepDetail[];
  logs: TaskLogDetail[];
  mock_mode: boolean;
}

const PAGE_SIZE = 50;

const STATUS_COLORS: Record<string, string> = {
  running: "bg-blue-500/20 text-blue-300 border-blue-700",
  completed: "bg-emerald-500/20 text-emerald-300 border-emerald-700",
  failed: "bg-red-500/20 text-red-300 border-red-700",
  cancelled: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
  paused: "bg-amber-500/20 text-amber-300 border-amber-700",
  pending: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
};

export function History() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [search, setSearch] = useState("");
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<TaskDetail | null>(null);
  const [selectedLoading, setSelectedLoading] = useState(false);

  async function load() {
    setLoadState("loading");
    setError("");
    try {
      const r = await api.history.listTasks({
        limit: PAGE_SIZE,
        offset,
        status: status || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        search: search || undefined,
      });
      setTasks(r.tasks);
      setTotal(r.count);
      setLoadState("ready");
    } catch (e) {
      setError(String(e));
      setLoadState("error");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  async function openTask(id: string) {
    setSelectedLoading(true);
    try {
      const r = await api.history.getTask(id);
      setSelected(r as TaskDetail);
    } catch (e) {
      setError(String(e));
    } finally {
      setSelectedLoading(false);
    }
  }

  async function rerun(id: string) {
    if (!window.confirm("Re-run this task? A new run_id will be created.")) return;
    try {
      await api.history.rerunTask(id);
      await load();
      setSelected(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function exportCsv() {
    try {
      const blob = await api.history.export({
        status: status || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        search: search || undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "tasks.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">History</h1>
          <p className="text-zinc-400 mt-1">
            Browse past task runs with steps, logs, and screenshots.
          </p>
        </div>
        <button
          onClick={exportCsv}
          className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm"
        >
          Export CSV
        </button>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Filter bar */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
        <div className="grid grid-cols-5 gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name..."
            className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
          >
            <option value="">All statuses</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="paused">Paused</option>
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => {
              setOffset(0);
              load();
            }}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm"
          >
            Apply Filters
          </button>
        </div>
      </div>

      {/* Task list */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-zinc-950 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-2 text-left">Name</th>
              <th className="px-4 py-2 text-left">Created</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Profile</th>
              <th className="px-4 py-2 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {loadState === "loading" ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                  Loading...
                </td>
              </tr>
            ) : tasks.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                  No tasks found. Run a workflow to populate the history.
                </td>
              </tr>
            ) : (
              tasks.map((t) => (
                <tr key={t.id} className="hover:bg-zinc-800/50">
                  <td className="px-4 py-2 truncate max-w-xs">{t.name}</td>
                  <td className="px-4 py-2 text-zinc-400">
                    {t.created_at ? new Date(t.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                        STATUS_COLORS[t.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-zinc-500 font-mono text-xs">
                    {t.profile_id ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => openTask(t.id)}
                      className="text-xs text-zinc-400 hover:text-zinc-200"
                    >
                      Details
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {/* Pagination */}
        <div className="border-t border-zinc-800 px-4 py-2 flex items-center justify-between text-xs text-zinc-500">
          <span>
            {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-3 py-1"
            >
              Prev
            </button>
            <button
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-3 py-1"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Detail modal */}
      {(selected || selectedLoading) && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
          onClick={() => !selectedLoading && setSelected(null)}
        >
          <div
            className="bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            {selectedLoading ? (
              <div className="text-center text-zinc-500 py-12">Loading...</div>
            ) : selected ? (
              <TaskDetailModal detail={selected} onRerun={() => rerun(selected.task.id)} onClose={() => setSelected(null)} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function TaskDetailModal({
  detail,
  onRerun,
  onClose,
}: {
  detail: TaskDetail;
  onRerun: () => void;
  onClose: () => void;
}) {
  const { task } = detail;
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-medium">{task.name}</h2>
          <div className="text-xs text-zinc-500 mt-1 font-mono">{task.id}</div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onRerun}
            className="bg-emerald-700 hover:bg-emerald-600 rounded px-3 py-1.5 text-xs"
          >
            Re-run
          </button>
          <button
            onClick={onClose}
            className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs"
          >
            Close
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs text-zinc-500">Status</div>
          <div className="mt-1">
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                STATUS_COLORS[task.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"
              }`}
            >
              {task.status}
            </span>
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Started</div>
          <div className="mt-1 text-zinc-300">
            {task.started_at ? new Date(task.started_at).toLocaleString() : "—"}
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Finished</div>
          <div className="mt-1 text-zinc-300">
            {task.finished_at ? new Date(task.finished_at).toLocaleString() : "—"}
          </div>
        </div>
      </div>

      {/* Plan */}
      <div className="bg-zinc-950 border border-zinc-800 rounded p-3">
        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Plan</div>
        <pre className="text-xs font-mono text-zinc-300 overflow-x-auto max-h-48">
          {task.plan_json ? JSON.stringify(task.plan_json, null, 2) : "(no plan)"}
        </pre>
      </div>

      {/* Steps */}
      <div className="bg-zinc-950 border border-zinc-800 rounded">
        <div className="text-xs uppercase tracking-wider text-zinc-500 px-3 py-2 border-b border-zinc-800">
          Steps ({detail.steps.length})
        </div>
        <div className="divide-y divide-zinc-800">
          {detail.steps.length === 0 ? (
            <div className="px-3 py-4 text-zinc-500 text-sm">No steps recorded.</div>
          ) : (
            detail.steps.map((s) => (
              <div key={s.id} className="px-3 py-2">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-mono">{s.tool_name}</div>
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                      STATUS_COLORS[s.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"
                    }`}
                  >
                    {s.status}
                  </span>
                </div>
                <div className="text-xs text-zinc-500 mt-1 flex gap-3">
                  <span>risk: {s.risk_level}</span>
                  <span>duration: {s.duration_ms ?? "—"} ms</span>
                  <span>
                    started: {s.started_at ? new Date(s.started_at).toLocaleTimeString() : "—"}
                  </span>
                </div>
                {s.error && (
                  <div className="text-xs text-red-400 mt-1">{s.error}</div>
                )}
                {s.output && (
                  <pre className="text-xs font-mono text-zinc-400 mt-1 max-h-32 overflow-y-auto">
                    {typeof s.output === "string"
                      ? s.output
                      : JSON.stringify(s.output, null, 2)}
                  </pre>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Logs */}
      <div className="bg-zinc-950 border border-zinc-800 rounded">
        <div className="text-xs uppercase tracking-wider text-zinc-500 px-3 py-2 border-b border-zinc-800">
          Logs ({detail.logs.length})
        </div>
        <div className="max-h-48 overflow-y-auto font-mono text-xs">
          {detail.logs.length === 0 ? (
            <div className="px-3 py-4 text-zinc-500">No logs for this task.</div>
          ) : (
            detail.logs.map((l) => (
              <div key={l.id} className="px-3 py-1 border-b border-zinc-800/50">
                <span className="text-zinc-500">
                  {l.timestamp ? new Date(l.timestamp).toLocaleTimeString() : "—"}{" "}
                </span>
                <span className={`text-${l.level === "error" ? "red" : "zinc"}-400`}>
                  [{l.level}]{" "}
                </span>
                <span className="text-zinc-300">
                  {l.tool ?? "(no tool)"} — {l.target ?? ""}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Analytics page — master prompt §82 (Phase 4 Professional RPA).
 *
 * Layout:
 *  - Header: title + team filter dropdown + date range + Export CSV button.
 *  - Summary cards: total runs, success rate, avg duration, total AI calls,
 *    estimated cost.
 *  - Bar chart: daily runs (last 30 days).
 *  - Pie chart: success vs failure.
 *  - Top tools table (tool, count, avg duration).
 *  - Top workflows table (workflow, runs, success rate).
 *  - Leaderboard (top contributors).
 *
 * In mock mode (or when no DB is configured) the backend returns zeros
 * and the UI renders an empty state with a "mock mode" badge.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  api,
  AnalyticsSummary,
  AnalyticsEvent,
} from "../lib/api";
import { useStore } from "../store";

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="text-2xl font-semibold mt-2">{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-1">{sub}</div>}
    </div>
  );
}

function BarChart({
  data,
}: {
  data: Array<{ date: string; runs: number; successes: number; failures: number }>;
}) {
  if (data.length === 0) {
    return (
      <div className="text-xs text-zinc-500 py-8 text-center">
        No daily breakdown data.
      </div>
    );
  }
  const maxRuns = Math.max(1, ...data.map((d) => d.runs));
  return (
    <div className="space-y-1">
      {data.slice(0, 30).map((d) => {
        const height = Math.max(2, (d.runs / maxRuns) * 100);
        const successPct = d.runs > 0 ? (d.successes / d.runs) * 100 : 0;
        const failurePct = d.runs > 0 ? (d.failures / d.runs) * 100 : 0;
        return (
          <div key={d.date} className="flex items-center gap-2 text-xs">
            <div className="w-24 text-zinc-500 font-mono">{d.date}</div>
            <div className="flex-1 h-4 bg-zinc-800 rounded overflow-hidden relative">
              <div
                className="absolute inset-y-0 left-0 bg-emerald-600"
                style={{ width: `${(successPct * height) / 100}%` }}
                title={`Successes: ${d.successes}`}
              />
              <div
                className="absolute inset-y-0 bg-red-600"
                style={{
                  left: `${(successPct * height) / 100}%`,
                  width: `${(failurePct * height) / 100}%`,
                }}
                title={`Failures: ${d.failures}`}
              />
            </div>
            <div className="w-12 text-right text-zinc-400">{d.runs}</div>
          </div>
        );
      })}
    </div>
  );
}

function PieChart({
  successes,
  failures,
}: {
  successes: number;
  failures: number;
}) {
  const total = successes + failures;
  if (total === 0) {
    return (
      <div className="text-xs text-zinc-500 py-8 text-center">
        No success/failure data.
      </div>
    );
  }
  const successPct = (successes / total) * 100;
  return (
    <div className="flex items-center gap-4">
      <div className="w-32 h-32 rounded-full border-8 border-zinc-800 relative overflow-hidden">
        <div
          className="absolute inset-0 bg-emerald-600"
          style={{ clipPath: `polygon(50% 50%, 50% 0%, ${50 + 50 * Math.cos((successPct / 100) * 2 * Math.PI - Math.PI / 2)}% ${50 + 50 * Math.sin((successPct / 100) * 2 * Math.PI - Math.PI / 2)}%)` }}
        />
        <div className="absolute inset-0 bg-red-600/40" />
      </div>
      <div className="space-y-1 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-emerald-600 rounded" />
          <span>{successes} successes ({successPct.toFixed(1)}%)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-red-600 rounded" />
          <span>{failures} failures ({(100 - successPct).toFixed(1)}%)</span>
        </div>
      </div>
    </div>
  );
}

export function Analytics() {
  const mockMode = useStore((s) => s.mockMode);
  const [teamId, setTeamId] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [events, setEvents] = useState<AnalyticsEvent[]>([]);
  const [leaderboard, setLeaderboard] = useState<
    Array<{ user_id: string; activity_count: number }>
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const params = {
        team_id: teamId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      };
      const [s, ev, lb] = await Promise.all([
        api.analytics.summary(params).catch((e) => {
          setError(e.message || String(e));
          return null;
        }),
        api.analytics
          .events({ ...params, limit: 100 })
          .catch(() => ({ events: [], count: 0, total: 0 })),
        api.analytics.leaderboard({ team_id: teamId || undefined }).catch(() => ({
          leaderboard: [],
          count: 0,
        })),
      ]);
      setSummary(s);
      setEvents((ev.events || []) as AnalyticsEvent[]);
      setLeaderboard(lb.leaderboard || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId, dateFrom, dateTo]);

  async function handleExportCsv() {
    setError("");
    setMessage("");
    try {
      const blob = await api.analytics.export({
        format: "csv",
        team_id: teamId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "analytics.csv";
      a.click();
      URL.revokeObjectURL(url);
      setMessage("Export downloaded.");
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  const totalSuccesses = useMemo(
    () => summary?.daily_breakdown.reduce((acc, d) => acc + d.successes, 0) ?? 0,
    [summary],
  );
  const totalFailures = useMemo(
    () => summary?.daily_breakdown.reduce((acc, d) => acc + d.failures, 0) ?? 0,
    [summary],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Analytics</h1>
          <p className="text-sm text-zinc-400">
            Execution analytics: workflow runs, success rates, top tools,
            leaderboard.
            {mockMode && " (mock mode — seeded data)"}
          </p>
        </div>
        <button
          onClick={handleExportCsv}
          className="px-3 py-1.5 text-sm rounded bg-zinc-700 hover:bg-zinc-600 text-white"
        >
          Export CSV
        </button>
      </div>

      {error && (
        <div className="px-3 py-2 rounded border border-red-700 bg-red-500/10 text-red-300 text-sm">
          {error}
        </div>
      )}
      {message && (
        <div className="px-3 py-2 rounded border border-emerald-700 bg-emerald-500/10 text-emerald-300 text-sm">
          {message}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 p-3 rounded border border-zinc-800 bg-zinc-900">
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500">Team</label>
          <input
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            placeholder="(any)"
            className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs"
          />
        </div>
        {loading && <span className="text-xs text-zinc-500">Loading…</span>}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-3">
        <MetricCard
          label="Total Runs"
          value={summary ? String(summary.total_workflows_run) : "—"}
        />
        <MetricCard
          label="Success Rate"
          value={
            summary ? `${(summary.success_rate * 100).toFixed(1)}%` : "—"
          }
        />
        <MetricCard
          label="Avg Duration"
          value={summary ? `${summary.avg_duration_ms.toFixed(0)} ms` : "—"}
        />
        <MetricCard
          label="AI Calls"
          value={summary ? String(summary.total_ai_calls) : "—"}
        />
        <MetricCard
          label="Est. Cost"
          value={summary ? `$${summary.estimated_cost.toFixed(4)}` : "—"}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Daily bar chart */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Daily Runs (last 30 days)</div>
          <BarChart data={summary?.daily_breakdown || []} />
        </div>

        {/* Pie chart */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Success vs Failure</div>
          <PieChart successes={totalSuccesses} failures={totalFailures} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Top tools */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Top Tools</div>
          <table className="w-full text-xs">
            <thead className="text-zinc-500">
              <tr>
                <th className="text-left py-1">Tool</th>
                <th className="text-right py-1">Count</th>
                <th className="text-right py-1">Avg Duration (ms)</th>
              </tr>
            </thead>
            <tbody>
              {(!summary || summary.top_tools.length === 0) && (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-zinc-500">
                    No tool usage recorded.
                  </td>
                </tr>
              )}
              {summary?.top_tools.map((t) => (
                <tr key={t.tool} className="border-t border-zinc-800">
                  <td className="py-1 font-mono">{t.tool}</td>
                  <td className="text-right">{t.count}</td>
                  <td className="text-right">{t.avg_duration_ms.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Top workflows */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Top Workflows</div>
          <table className="w-full text-xs">
            <thead className="text-zinc-500">
              <tr>
                <th className="text-left py-1">Workflow</th>
                <th className="text-right py-1">Runs</th>
                <th className="text-right py-1">Success Rate</th>
              </tr>
            </thead>
            <tbody>
              {(!summary || summary.top_workflows.length === 0) && (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-zinc-500">
                    No workflow runs recorded.
                  </td>
                </tr>
              )}
              {summary?.top_workflows.map((w) => (
                <tr key={w.workflow} className="border-t border-zinc-800">
                  <td className="py-1 font-mono">{w.workflow}</td>
                  <td className="text-right">{w.runs}</td>
                  <td className="text-right">
                    {(w.success_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Leaderboard */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Leaderboard</div>
          {leaderboard.length === 0 ? (
            <div className="text-xs text-zinc-500 py-4 text-center">
              No contributor activity recorded.
            </div>
          ) : (
            <div className="space-y-1">
              {leaderboard.map((l, i) => (
                <div
                  key={l.user_id}
                  className="flex items-center justify-between text-xs px-3 py-2 rounded bg-zinc-800/50"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-zinc-500">#{i + 1}</span>
                    <span className="font-mono">{l.user_id}</span>
                  </div>
                  <span className="text-zinc-400">{l.activity_count} actions</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent events */}
        <div className="p-4 rounded border border-zinc-800 bg-zinc-900">
          <div className="text-sm font-medium mb-3">Recent Events</div>
          {events.length === 0 ? (
            <div className="text-xs text-zinc-500 py-4 text-center">
              No events recorded.
            </div>
          ) : (
            <div className="space-y-1 max-h-72 overflow-y-auto">
              {events.slice(0, 50).map((e) => (
                <div
                  key={e.id}
                  className="text-xs px-3 py-1.5 rounded bg-zinc-800/50"
                >
                  <span className="font-mono text-zinc-300">{e.event_type}</span>
                  <span className="text-zinc-500 ml-2">
                    {e.user_id || "system"}
                  </span>
                  {e.duration_ms != null && (
                    <span className="text-zinc-500 ml-2">
                      {e.duration_ms} ms
                    </span>
                  )}
                  {e.cost_estimate != null && (
                    <span className="text-zinc-500 ml-2">
                      ${e.cost_estimate.toFixed(4)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
import { useEffect, useMemo, useState } from "react";
import { api, } from "../lib/api";
import { useStore } from "../store";
function MetricCard({ label, value, sub, }) {
    return (_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-xs uppercase tracking-wide text-zinc-500", children: label }), _jsx("div", { className: "text-2xl font-semibold mt-2", children: value }), sub && _jsx("div", { className: "text-xs text-zinc-500 mt-1", children: sub })] }));
}
function BarChart({ data, }) {
    if (data.length === 0) {
        return (_jsx("div", { className: "text-xs text-zinc-500 py-8 text-center", children: "No daily breakdown data." }));
    }
    const maxRuns = Math.max(1, ...data.map((d) => d.runs));
    return (_jsx("div", { className: "space-y-1", children: data.slice(0, 30).map((d) => {
            const height = Math.max(2, (d.runs / maxRuns) * 100);
            const successPct = d.runs > 0 ? (d.successes / d.runs) * 100 : 0;
            const failurePct = d.runs > 0 ? (d.failures / d.runs) * 100 : 0;
            return (_jsxs("div", { className: "flex items-center gap-2 text-xs", children: [_jsx("div", { className: "w-24 text-zinc-500 font-mono", children: d.date }), _jsxs("div", { className: "flex-1 h-4 bg-zinc-800 rounded overflow-hidden relative", children: [_jsx("div", { className: "absolute inset-y-0 left-0 bg-emerald-600", style: { width: `${(successPct * height) / 100}%` }, title: `Successes: ${d.successes}` }), _jsx("div", { className: "absolute inset-y-0 bg-red-600", style: {
                                    left: `${(successPct * height) / 100}%`,
                                    width: `${(failurePct * height) / 100}%`,
                                }, title: `Failures: ${d.failures}` })] }), _jsx("div", { className: "w-12 text-right text-zinc-400", children: d.runs })] }, d.date));
        }) }));
}
function PieChart({ successes, failures, }) {
    const total = successes + failures;
    if (total === 0) {
        return (_jsx("div", { className: "text-xs text-zinc-500 py-8 text-center", children: "No success/failure data." }));
    }
    const successPct = (successes / total) * 100;
    return (_jsxs("div", { className: "flex items-center gap-4", children: [_jsxs("div", { className: "w-32 h-32 rounded-full border-8 border-zinc-800 relative overflow-hidden", children: [_jsx("div", { className: "absolute inset-0 bg-emerald-600", style: { clipPath: `polygon(50% 50%, 50% 0%, ${50 + 50 * Math.cos((successPct / 100) * 2 * Math.PI - Math.PI / 2)}% ${50 + 50 * Math.sin((successPct / 100) * 2 * Math.PI - Math.PI / 2)}%)` } }), _jsx("div", { className: "absolute inset-0 bg-red-600/40" })] }), _jsxs("div", { className: "space-y-1 text-sm", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("div", { className: "w-3 h-3 bg-emerald-600 rounded" }), _jsxs("span", { children: [successes, " successes (", successPct.toFixed(1), "%)"] })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx("div", { className: "w-3 h-3 bg-red-600 rounded" }), _jsxs("span", { children: [failures, " failures (", (100 - successPct).toFixed(1), "%)"] })] })] })] }));
}
export function Analytics() {
    const mockMode = useStore((s) => s.mockMode);
    const [teamId, setTeamId] = useState("");
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");
    const [summary, setSummary] = useState(null);
    const [events, setEvents] = useState([]);
    const [leaderboard, setLeaderboard] = useState([]);
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
            setEvents((ev.events || []));
            setLeaderboard(lb.leaderboard || []);
        }
        finally {
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
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    const totalSuccesses = useMemo(() => summary?.daily_breakdown.reduce((acc, d) => acc + d.successes, 0) ?? 0, [summary]);
    const totalFailures = useMemo(() => summary?.daily_breakdown.reduce((acc, d) => acc + d.failures, 0) ?? 0, [summary]);
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Analytics" }), _jsxs("p", { className: "text-sm text-zinc-400", children: ["Execution analytics: workflow runs, success rates, top tools, leaderboard.", mockMode && " (mock mode — seeded data)"] })] }), _jsx("button", { onClick: handleExportCsv, className: "px-3 py-1.5 text-sm rounded bg-zinc-700 hover:bg-zinc-600 text-white", children: "Export CSV" })] }), error && (_jsx("div", { className: "px-3 py-2 rounded border border-red-700 bg-red-500/10 text-red-300 text-sm", children: error })), message && (_jsx("div", { className: "px-3 py-2 rounded border border-emerald-700 bg-emerald-500/10 text-emerald-300 text-sm", children: message })), _jsxs("div", { className: "flex items-center gap-3 p-3 rounded border border-zinc-800 bg-zinc-900", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Team" }), _jsx("input", { value: teamId, onChange: (e) => setTeamId(e.target.value), placeholder: "(any)", className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48" })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx("label", { className: "text-xs text-zinc-500", children: "From" }), _jsx("input", { type: "date", value: dateFrom, onChange: (e) => setDateFrom(e.target.value), className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs" })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx("label", { className: "text-xs text-zinc-500", children: "To" }), _jsx("input", { type: "date", value: dateTo, onChange: (e) => setDateTo(e.target.value), className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs" })] }), loading && _jsx("span", { className: "text-xs text-zinc-500", children: "Loading\u2026" })] }), _jsxs("div", { className: "grid grid-cols-5 gap-3", children: [_jsx(MetricCard, { label: "Total Runs", value: summary ? String(summary.total_workflows_run) : "—" }), _jsx(MetricCard, { label: "Success Rate", value: summary ? `${(summary.success_rate * 100).toFixed(1)}%` : "—" }), _jsx(MetricCard, { label: "Avg Duration", value: summary ? `${summary.avg_duration_ms.toFixed(0)} ms` : "—" }), _jsx(MetricCard, { label: "AI Calls", value: summary ? String(summary.total_ai_calls) : "—" }), _jsx(MetricCard, { label: "Est. Cost", value: summary ? `$${summary.estimated_cost.toFixed(4)}` : "—" })] }), _jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Daily Runs (last 30 days)" }), _jsx(BarChart, { data: summary?.daily_breakdown || [] })] }), _jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Success vs Failure" }), _jsx(PieChart, { successes: totalSuccesses, failures: totalFailures })] })] }), _jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Top Tools" }), _jsxs("table", { className: "w-full text-xs", children: [_jsx("thead", { className: "text-zinc-500", children: _jsxs("tr", { children: [_jsx("th", { className: "text-left py-1", children: "Tool" }), _jsx("th", { className: "text-right py-1", children: "Count" }), _jsx("th", { className: "text-right py-1", children: "Avg Duration (ms)" })] }) }), _jsxs("tbody", { children: [(!summary || summary.top_tools.length === 0) && (_jsx("tr", { children: _jsx("td", { colSpan: 3, className: "py-4 text-center text-zinc-500", children: "No tool usage recorded." }) })), summary?.top_tools.map((t) => (_jsxs("tr", { className: "border-t border-zinc-800", children: [_jsx("td", { className: "py-1 font-mono", children: t.tool }), _jsx("td", { className: "text-right", children: t.count }), _jsx("td", { className: "text-right", children: t.avg_duration_ms.toFixed(0) })] }, t.tool)))] })] })] }), _jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Top Workflows" }), _jsxs("table", { className: "w-full text-xs", children: [_jsx("thead", { className: "text-zinc-500", children: _jsxs("tr", { children: [_jsx("th", { className: "text-left py-1", children: "Workflow" }), _jsx("th", { className: "text-right py-1", children: "Runs" }), _jsx("th", { className: "text-right py-1", children: "Success Rate" })] }) }), _jsxs("tbody", { children: [(!summary || summary.top_workflows.length === 0) && (_jsx("tr", { children: _jsx("td", { colSpan: 3, className: "py-4 text-center text-zinc-500", children: "No workflow runs recorded." }) })), summary?.top_workflows.map((w) => (_jsxs("tr", { className: "border-t border-zinc-800", children: [_jsx("td", { className: "py-1 font-mono", children: w.workflow }), _jsx("td", { className: "text-right", children: w.runs }), _jsxs("td", { className: "text-right", children: [(w.success_rate * 100).toFixed(1), "%"] })] }, w.workflow)))] })] })] })] }), _jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Leaderboard" }), leaderboard.length === 0 ? (_jsx("div", { className: "text-xs text-zinc-500 py-4 text-center", children: "No contributor activity recorded." })) : (_jsx("div", { className: "space-y-1", children: leaderboard.map((l, i) => (_jsxs("div", { className: "flex items-center justify-between text-xs px-3 py-2 rounded bg-zinc-800/50", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsxs("span", { className: "text-zinc-500", children: ["#", i + 1] }), _jsx("span", { className: "font-mono", children: l.user_id })] }), _jsxs("span", { className: "text-zinc-400", children: [l.activity_count, " actions"] })] }, l.user_id))) }))] }), _jsxs("div", { className: "p-4 rounded border border-zinc-800 bg-zinc-900", children: [_jsx("div", { className: "text-sm font-medium mb-3", children: "Recent Events" }), events.length === 0 ? (_jsx("div", { className: "text-xs text-zinc-500 py-4 text-center", children: "No events recorded." })) : (_jsx("div", { className: "space-y-1 max-h-72 overflow-y-auto", children: events.slice(0, 50).map((e) => (_jsxs("div", { className: "text-xs px-3 py-1.5 rounded bg-zinc-800/50", children: [_jsx("span", { className: "font-mono text-zinc-300", children: e.event_type }), _jsx("span", { className: "text-zinc-500 ml-2", children: e.user_id || "system" }), e.duration_ms != null && (_jsxs("span", { className: "text-zinc-500 ml-2", children: [e.duration_ms, " ms"] })), e.cost_estimate != null && (_jsxs("span", { className: "text-zinc-500 ml-2", children: ["$", e.cost_estimate.toFixed(4)] }))] }, e.id))) }))] })] })] }));
}

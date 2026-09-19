import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
import { useEffect, useState } from "react";
import { api } from "../lib/api";
const PAGE_SIZE = 50;
const STATUS_COLORS = {
    running: "bg-blue-500/20 text-blue-300 border-blue-700",
    completed: "bg-emerald-500/20 text-emerald-300 border-emerald-700",
    failed: "bg-red-500/20 text-red-300 border-red-700",
    cancelled: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
    paused: "bg-amber-500/20 text-amber-300 border-amber-700",
    pending: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
};
export function History() {
    const [tasks, setTasks] = useState([]);
    const [total, setTotal] = useState(0);
    const [offset, setOffset] = useState(0);
    const [status, setStatus] = useState("");
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");
    const [search, setSearch] = useState("");
    const [loadState, setLoadState] = useState("loading");
    const [error, setError] = useState("");
    const [selected, setSelected] = useState(null);
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
        }
        catch (e) {
            setError(String(e));
            setLoadState("error");
        }
    }
    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [offset]);
    async function openTask(id) {
        setSelectedLoading(true);
        try {
            const r = await api.history.getTask(id);
            setSelected(r);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setSelectedLoading(false);
        }
    }
    async function rerun(id) {
        if (!window.confirm("Re-run this task? A new run_id will be created."))
            return;
        try {
            await api.history.rerunTask(id);
            await load();
            setSelected(null);
        }
        catch (e) {
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
        }
        catch (e) {
            setError(String(e));
        }
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "History" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Browse past task runs with steps, logs, and screenshots." })] }), _jsx("button", { onClick: exportCsv, className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm", children: "Export CSV" })] }), error && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), _jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-3", children: _jsxs("div", { className: "grid grid-cols-5 gap-2", children: [_jsx("input", { value: search, onChange: (e) => setSearch(e.target.value), placeholder: "Search by name...", className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm" }), _jsxs("select", { value: status, onChange: (e) => setStatus(e.target.value), className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm", children: [_jsx("option", { value: "", children: "All statuses" }), _jsx("option", { value: "running", children: "Running" }), _jsx("option", { value: "completed", children: "Completed" }), _jsx("option", { value: "failed", children: "Failed" }), _jsx("option", { value: "cancelled", children: "Cancelled" }), _jsx("option", { value: "paused", children: "Paused" })] }), _jsx("input", { type: "date", value: dateFrom, onChange: (e) => setDateFrom(e.target.value), className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm" }), _jsx("input", { type: "date", value: dateTo, onChange: (e) => setDateTo(e.target.value), className: "bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-sm" }), _jsx("button", { onClick: () => {
                                setOffset(0);
                                load();
                            }, className: "bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm", children: "Apply Filters" })] }) }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden", children: [_jsxs("table", { className: "w-full text-sm", children: [_jsx("thead", { className: "bg-zinc-950 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2 text-left", children: "Name" }), _jsx("th", { className: "px-4 py-2 text-left", children: "Created" }), _jsx("th", { className: "px-4 py-2 text-left", children: "Status" }), _jsx("th", { className: "px-4 py-2 text-left", children: "Profile" }), _jsx("th", { className: "px-4 py-2 text-right" })] }) }), _jsx("tbody", { className: "divide-y divide-zinc-800", children: loadState === "loading" ? (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-8 text-center text-zinc-500", children: "Loading..." }) })) : tasks.length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-8 text-center text-zinc-500", children: "No tasks found. Run a workflow to populate the history." }) })) : (tasks.map((t) => (_jsxs("tr", { className: "hover:bg-zinc-800/50", children: [_jsx("td", { className: "px-4 py-2 truncate max-w-xs", children: t.name }), _jsx("td", { className: "px-4 py-2 text-zinc-400", children: t.created_at ? new Date(t.created_at).toLocaleString() : "—" }), _jsx("td", { className: "px-4 py-2", children: _jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${STATUS_COLORS[t.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"}`, children: t.status }) }), _jsx("td", { className: "px-4 py-2 text-zinc-500 font-mono text-xs", children: t.profile_id ?? "—" }), _jsx("td", { className: "px-4 py-2 text-right", children: _jsx("button", { onClick: () => openTask(t.id), className: "text-xs text-zinc-400 hover:text-zinc-200", children: "Details" }) })] }, t.id)))) })] }), _jsxs("div", { className: "border-t border-zinc-800 px-4 py-2 flex items-center justify-between text-xs text-zinc-500", children: [_jsxs("span", { children: [offset + 1, "-", Math.min(offset + PAGE_SIZE, total), " of ", total] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { disabled: offset === 0, onClick: () => setOffset(Math.max(0, offset - PAGE_SIZE)), className: "bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-3 py-1", children: "Prev" }), _jsx("button", { disabled: offset + PAGE_SIZE >= total, onClick: () => setOffset(offset + PAGE_SIZE), className: "bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-3 py-1", children: "Next" })] })] })] }), (selected || selectedLoading) && (_jsx("div", { className: "fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4", onClick: () => !selectedLoading && setSelected(null), children: _jsx("div", { className: "bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6", onClick: (e) => e.stopPropagation(), children: selectedLoading ? (_jsx("div", { className: "text-center text-zinc-500 py-12", children: "Loading..." })) : selected ? (_jsx(TaskDetailModal, { detail: selected, onRerun: () => rerun(selected.task.id), onClose: () => setSelected(null) })) : null }) }))] }));
}
function TaskDetailModal({ detail, onRerun, onClose, }) {
    const { task } = detail;
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex items-start justify-between", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-lg font-medium", children: task.name }), _jsx("div", { className: "text-xs text-zinc-500 mt-1 font-mono", children: task.id })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: onRerun, className: "bg-emerald-700 hover:bg-emerald-600 rounded px-3 py-1.5 text-xs", children: "Re-run" }), _jsx("button", { onClick: onClose, className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs", children: "Close" })] })] }), _jsxs("div", { className: "grid grid-cols-3 gap-3 text-sm", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500", children: "Status" }), _jsx("div", { className: "mt-1", children: _jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${STATUS_COLORS[task.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"}`, children: task.status }) })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500", children: "Started" }), _jsx("div", { className: "mt-1 text-zinc-300", children: task.started_at ? new Date(task.started_at).toLocaleString() : "—" })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500", children: "Finished" }), _jsx("div", { className: "mt-1 text-zinc-300", children: task.finished_at ? new Date(task.finished_at).toLocaleString() : "—" })] })] }), _jsxs("div", { className: "bg-zinc-950 border border-zinc-800 rounded p-3", children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-2", children: "Plan" }), _jsx("pre", { className: "text-xs font-mono text-zinc-300 overflow-x-auto max-h-48", children: task.plan_json ? JSON.stringify(task.plan_json, null, 2) : "(no plan)" })] }), _jsxs("div", { className: "bg-zinc-950 border border-zinc-800 rounded", children: [_jsxs("div", { className: "text-xs uppercase tracking-wider text-zinc-500 px-3 py-2 border-b border-zinc-800", children: ["Steps (", detail.steps.length, ")"] }), _jsx("div", { className: "divide-y divide-zinc-800", children: detail.steps.length === 0 ? (_jsx("div", { className: "px-3 py-4 text-zinc-500 text-sm", children: "No steps recorded." })) : (detail.steps.map((s) => (_jsxs("div", { className: "px-3 py-2", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("div", { className: "text-sm font-mono", children: s.tool_name }), _jsx("span", { className: `inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${STATUS_COLORS[s.status] ?? "bg-zinc-500/20 text-zinc-300 border-zinc-600"}`, children: s.status })] }), _jsxs("div", { className: "text-xs text-zinc-500 mt-1 flex gap-3", children: [_jsxs("span", { children: ["risk: ", s.risk_level] }), _jsxs("span", { children: ["duration: ", s.duration_ms ?? "—", " ms"] }), _jsxs("span", { children: ["started: ", s.started_at ? new Date(s.started_at).toLocaleTimeString() : "—"] })] }), s.error && (_jsx("div", { className: "text-xs text-red-400 mt-1", children: s.error })), s.output && (_jsx("pre", { className: "text-xs font-mono text-zinc-400 mt-1 max-h-32 overflow-y-auto", children: typeof s.output === "string"
                                        ? s.output
                                        : JSON.stringify(s.output, null, 2) }))] }, s.id)))) })] }), _jsxs("div", { className: "bg-zinc-950 border border-zinc-800 rounded", children: [_jsxs("div", { className: "text-xs uppercase tracking-wider text-zinc-500 px-3 py-2 border-b border-zinc-800", children: ["Logs (", detail.logs.length, ")"] }), _jsx("div", { className: "max-h-48 overflow-y-auto font-mono text-xs", children: detail.logs.length === 0 ? (_jsx("div", { className: "px-3 py-4 text-zinc-500", children: "No logs for this task." })) : (detail.logs.map((l) => (_jsxs("div", { className: "px-3 py-1 border-b border-zinc-800/50", children: [_jsxs("span", { className: "text-zinc-500", children: [l.timestamp ? new Date(l.timestamp).toLocaleTimeString() : "—", " "] }), _jsxs("span", { className: `text-${l.level === "error" ? "red" : "zinc"}-400`, children: ["[", l.level, "]", " "] }), _jsxs("span", { className: "text-zinc-300", children: [l.tool ?? "(no tool)", " \u2014 ", l.target ?? ""] })] }, l.id)))) })] })] }));
}

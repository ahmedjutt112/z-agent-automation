import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * AI Assistant page — master prompt §83 (Phase 5 — Advanced AI OS Assistant).
 *
 * Distinct from the AIAgent chat page: this one exposes high-level
 * contextual automation goals ("prepare for my next meeting", "morning
 * routine", "research a topic", "organise files by context", "end-of-day
 * summary") + a calendar peek.
 *
 * CRITICAL (§83): every external action must still pass through permissions
 * and user-defined policies. Every plan-returning endpoint returns
 * executed=false; the user must click "Approve & Run" before the plan is
 * sent to /assistant/run-meeting-prep (or /task/run).
 *
 * Master prompt §85: the top of the page has a 3-way mode selector
 * (Assist / Guided / Autonomous) that toggles how aggressive the assistant
 * is allowed to be.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
export function Assistant() {
    const [mode, setMode] = useState("guided");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [planModal, setPlanModal] = useState(null);
    const [summaryModal, setSummaryModal] = useState(null);
    // Calendar — next 5 events, polled every 60s.
    const [events, setEvents] = useState([]);
    const [calendarProvider, setCalendarProvider] = useState("");
    const refreshCalendar = useCallback(async () => {
        try {
            const r = await api.assistant.calendarEvents({ max_results: 5 });
            setEvents(r.events);
            setCalendarProvider(r.provider);
        }
        catch {
            // Service unreachable — leave the calendar empty.
        }
    }, []);
    useEffect(() => {
        refreshCalendar();
        const id = window.setInterval(refreshCalendar, 60_000);
        return () => window.clearInterval(id);
    }, [refreshCalendar]);
    async function withBusy(fn) {
        setBusy(true);
        setError(null);
        try {
            return await fn();
        }
        catch (err) {
            setError(err.message);
            return null;
        }
        finally {
            setBusy(false);
        }
    }
    async function prepareMeeting() {
        const r = await withBusy(() => api.assistant.prepareMeeting());
        if (!r)
            return;
        setPlanModal({
            plan: r.plan,
            source: "Prepare for meeting",
            meeting: r.meeting,
            dashboardUrl: r.dashboard_url,
            openedApps: r.opened_apps,
            openedTabs: r.opened_tabs,
        });
    }
    async function morningRoutine() {
        const r = await withBusy(() => api.assistant.morningRoutine());
        if (!r)
            return;
        setPlanModal({ plan: r.plan, source: "Morning routine" });
    }
    async function endOfDaySummary() {
        const r = await withBusy(() => api.assistant.endOfDaySummary());
        if (!r)
            return;
        setSummaryModal(r);
    }
    async function runPlan(plan) {
        const r = await withBusy(() => api.assistant.runMeetingPrep(plan));
        if (!r)
            return;
        setPlanModal(null);
        setError(`Plan started. run_id=${r.run_id}`);
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-start justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "AI Assistant" }), _jsx("p", { className: "text-zinc-400 mt-1 text-sm", children: "Phase 5 \u2014 contextual multi-step automation (master prompt \u00A783). Plans are generated but never auto-executed \u2014 you must approve each one." })] }), _jsx(ModeSelector, { mode: mode, onChange: setMode })] }), error && (_jsx("div", { className: "bg-red-900/30 border border-red-700 text-red-200 rounded px-3 py-2 text-sm", children: error })), _jsxs("section", { className: "grid grid-cols-1 md:grid-cols-2 gap-3", children: [_jsx(ActionCard, { title: "Prepare for my next meeting", subtitle: "Generate a meeting-prep plan (open agenda, tabs, notes app, presentation, dashboard).", onClick: prepareMeeting, disabled: busy, accent: "emerald" }), _jsx(ActionCard, { title: "Morning routine", subtitle: "Open mail, calendar, and today's tasks.", onClick: morningRoutine, disabled: busy, accent: "blue" }), _jsx(ActionCard, { title: "End of day summary", subtitle: "Summarise today's automation activities.", onClick: endOfDaySummary, disabled: busy, accent: "amber" }), _jsx(ActionCard, { title: "Refresh calendar", subtitle: `Re-fetch the next 5 events (provider: ${calendarProvider || "—"}).`, onClick: refreshCalendar, disabled: busy, accent: "zinc" })] }), _jsx(ResearchForm, { disabled: busy, onSubmit: async (topic, depth) => {
                    const r = await withBusy(() => api.assistant.research(topic, depth));
                    if (!r)
                        return;
                    setPlanModal({ plan: r.plan, source: `Research: ${topic}` });
                } }), _jsx(OrganizeFilesForm, { disabled: busy, onSubmit: async (ctx) => {
                    const r = await withBusy(() => api.assistant.organizeFiles(ctx));
                    if (!r)
                        return;
                    setPlanModal({ plan: r.plan, source: "Organise files" });
                } }), _jsxs("section", { className: "bg-zinc-900 rounded-lg border border-zinc-800 p-4", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm text-zinc-400", children: "Upcoming events" }), _jsx("div", { className: "mt-1 font-medium", children: "Next 5 events" })] }), calendarProvider && (_jsxs("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: ["provider: ", calendarProvider] }))] }), events.length === 0 ? (_jsx("div", { className: "mt-3 text-sm text-zinc-500", children: "No upcoming events." })) : (_jsx("ul", { className: "mt-3 space-y-2", children: events.map((e) => (_jsxs("li", { className: "bg-zinc-800 rounded px-3 py-2 text-sm flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "font-medium", children: e.title }), _jsxs("div", { className: "text-xs text-zinc-400 mt-0.5", children: [new Date(e.start_at).toLocaleString(), " \u2014", " ", e.attendees?.length || 0, " attendee(s)"] })] }), e.meeting_link && (_jsx("a", { href: e.meeting_link, target: "_blank", rel: "noreferrer", className: "text-xs text-blue-300 hover:underline", children: "Join" }))] }, e.id))) }))] }), planModal && (_jsx(PlanApprovalModal, { state: planModal, onClose: () => setPlanModal(null), onApprove: () => runPlan(planModal.plan), busy: busy })), summaryModal && (_jsx(SummaryModal, { summary: summaryModal, onClose: () => setSummaryModal(null) }))] }));
}
// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function ModeSelector({ mode, onChange, }) {
    return (_jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-1 flex gap-1", children: ["assist", "guided", "autonomous"].map((m) => (_jsxs("label", { className: `px-3 py-1.5 text-xs uppercase tracking-wider rounded cursor-pointer transition-colors ${mode === m
                ? "bg-zinc-700 text-white"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"}`, children: [_jsx("input", { type: "radio", name: "assistant-mode", value: m, checked: mode === m, onChange: () => onChange(m), className: "sr-only" }), m] }, m))) }));
}
function ActionCard({ title, subtitle, onClick, disabled, accent, }) {
    const accentClass = {
        emerald: "hover:border-emerald-500",
        blue: "hover:border-blue-500",
        amber: "hover:border-amber-500",
        zinc: "hover:border-zinc-500",
    }[accent];
    return (_jsxs("button", { onClick: onClick, disabled: disabled, className: `bg-zinc-800 rounded-lg p-4 text-left border border-zinc-700 transition-colors ${accentClass} disabled:opacity-50 disabled:cursor-not-allowed`, children: [_jsx("div", { className: "font-medium", children: title }), _jsx("div", { className: "text-sm text-zinc-400 mt-1", children: subtitle })] }));
}
function ResearchForm({ disabled, onSubmit, }) {
    const [topic, setTopic] = useState("");
    const [depth, setDepth] = useState(3);
    return (_jsxs("section", { className: "bg-zinc-900 rounded-lg border border-zinc-800 p-4", children: [_jsx("div", { className: "text-sm text-zinc-400", children: "Research a topic" }), _jsxs("div", { className: "mt-2 flex flex-col md:flex-row gap-2", children: [_jsx("input", { type: "text", value: topic, onChange: (e) => setTopic(e.target.value), placeholder: "e.g. AI automation frameworks", className: "flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx("label", { className: "text-xs text-zinc-400", children: "Depth" }), _jsx("input", { type: "range", min: 1, max: 5, value: depth, onChange: (e) => setDepth(Number(e.target.value)), className: "w-32" }), _jsx("span", { className: "text-xs text-zinc-300 w-4", children: depth })] }), _jsx("button", { onClick: () => topic.trim() && onSubmit(topic.trim(), depth), disabled: disabled || !topic.trim(), className: "bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium", children: "Generate Plan" })] })] }));
}
function OrganizeFilesForm({ disabled, onSubmit, }) {
    const [project, setProject] = useState("");
    const [attendees, setAttendees] = useState("");
    const [dateStart, setDateStart] = useState("");
    const [dateEnd, setDateEnd] = useState("");
    return (_jsxs("section", { className: "bg-zinc-900 rounded-lg border border-zinc-800 p-4", children: [_jsx("div", { className: "text-sm text-zinc-400", children: "Organise files by context" }), _jsxs("div", { className: "mt-2 grid grid-cols-1 md:grid-cols-2 gap-2", children: [_jsx("input", { type: "text", value: project, onChange: (e) => setProject(e.target.value), placeholder: "Project name", className: "bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" }), _jsx("input", { type: "text", value: attendees, onChange: (e) => setAttendees(e.target.value), placeholder: "Attendees (comma-separated)", className: "bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" }), _jsx("input", { type: "date", value: dateStart, onChange: (e) => setDateStart(e.target.value), className: "bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" }), _jsx("input", { type: "date", value: dateEnd, onChange: (e) => setDateEnd(e.target.value), className: "bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" })] }), _jsx("button", { onClick: () => {
                    const ctx = {};
                    if (project.trim())
                        ctx.project = project.trim();
                    if (attendees.trim())
                        ctx.attendees = attendees
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean);
                    if (dateStart && dateEnd)
                        ctx.date_range = { start: dateStart, end: dateEnd };
                    onSubmit(ctx);
                }, disabled: disabled, className: "mt-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium", children: "Generate Plan" })] }));
}
function PlanApprovalModal({ state, onClose, onApprove, busy, }) {
    const { plan, source, meeting, dashboardUrl, openedApps, openedTabs } = state;
    return (_jsx("div", { className: "fixed inset-0 bg-black/70 flex items-center justify-center z-50", children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-full max-w-2xl max-h-[80vh] overflow-auto", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: source }), _jsx("div", { className: "text-lg font-medium mt-1", children: plan.goal })] }), _jsx("button", { onClick: onClose, className: "text-zinc-400 hover:text-zinc-200 text-sm", children: "Close" })] }), meeting && (_jsxs("div", { className: "mt-3 bg-zinc-800 rounded p-3 text-sm", children: [_jsx("div", { className: "text-xs text-zinc-400", children: "Meeting" }), _jsx("div", { className: "mt-1 font-medium", children: meeting.title }), _jsxs("div", { className: "text-xs text-zinc-400 mt-0.5", children: [new Date(meeting.start_at).toLocaleString(), " \u2014", " ", meeting.attendees?.length || 0, " attendee(s)"] }), dashboardUrl && (_jsx("a", { href: dashboardUrl, target: "_blank", rel: "noreferrer", className: "text-xs text-blue-300 hover:underline mt-1 inline-block", children: "Open dashboard" }))] })), _jsxs("div", { className: "mt-3", children: [_jsxs("div", { className: "text-xs text-zinc-400 mb-1", children: ["Proposed plan (", plan.steps.length, " steps)"] }), _jsx("ol", { className: "text-sm space-y-1", children: plan.steps.map((s) => (_jsxs("li", { className: "bg-zinc-800 rounded px-3 py-2", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsxs("span", { className: "text-zinc-500", children: ["#", s.id] }), " ", _jsx("span", { className: "font-mono text-xs bg-zinc-700 px-1 rounded", children: s.action })] }), _jsxs("span", { className: `text-xs ${s.risk_level === "critical"
                                                    ? "text-red-400"
                                                    : s.risk_level === "high"
                                                        ? "text-amber-400"
                                                        : s.risk_level === "medium"
                                                            ? "text-yellow-400"
                                                            : "text-emerald-400"}`, children: ["[", s.risk_level, "]"] })] }), Object.keys(s.args || {}).length > 0 && (_jsx("pre", { className: "mt-1 text-xs text-zinc-400 overflow-x-auto", children: JSON.stringify(s.args, null, 2) }))] }, s.id))) })] }), (openedApps?.length || openedTabs?.length) && (_jsxs("div", { className: "mt-3 grid grid-cols-2 gap-2 text-xs", children: [openedApps && openedApps.length > 0 && (_jsxs("div", { children: [_jsx("div", { className: "text-zinc-400 mb-1", children: "Apps to open" }), _jsx("ul", { className: "space-y-0.5", children: openedApps.map((a) => (_jsx("li", { className: "font-mono", children: a }, a))) })] })), openedTabs && openedTabs.length > 0 && (_jsxs("div", { children: [_jsx("div", { className: "text-zinc-400 mb-1", children: "Tabs to open" }), _jsx("ul", { className: "space-y-0.5", children: openedTabs.map((t) => (_jsx("li", { className: "font-mono truncate", children: t }, t))) })] }))] })), _jsxs("div", { className: "mt-4 flex justify-end gap-2", children: [_jsx("button", { onClick: onClose, className: "bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded text-sm", children: "Cancel" }), _jsx("button", { onClick: onApprove, disabled: busy, className: "bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium", children: "Approve & Run" })] }), _jsx("div", { className: "mt-2 text-xs text-zinc-500", children: "Per master prompt \u00A766, every step still passes through the permission engine before executing." })] }) }));
}
function SummaryModal({ summary, onClose, }) {
    return (_jsx("div", { className: "fixed inset-0 bg-black/70 flex items-center justify-center z-50", children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-full max-w-2xl max-h-[80vh] overflow-auto", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: "End of day summary" }), _jsx("div", { className: "text-lg font-medium mt-1", children: summary.date })] }), _jsx("button", { onClick: onClose, className: "text-zinc-400 hover:text-zinc-200 text-sm", children: "Close" })] }), summary.mock_mode && (_jsx("div", { className: "mt-3 text-xs text-amber-400", children: "Mock mode \u2014 no real automation runs were recorded today." })), _jsxs("div", { className: "mt-3 grid grid-cols-2 gap-3 text-sm", children: [_jsxs("div", { className: "bg-zinc-800 rounded p-3", children: [_jsx("div", { className: "text-xs text-zinc-400", children: "Total runs" }), _jsx("div", { className: "text-2xl font-semibold", children: summary.total_runs })] }), _jsxs("div", { className: "bg-zinc-800 rounded p-3", children: [_jsx("div", { className: "text-xs text-zinc-400", children: "Total tasks" }), _jsx("div", { className: "text-2xl font-semibold", children: summary.total_tasks })] })] }), summary.next_meeting && (_jsxs("div", { className: "mt-3 bg-zinc-800 rounded p-3 text-sm", children: [_jsx("div", { className: "text-xs text-zinc-400", children: "Next meeting" }), _jsx("div", { className: "mt-1 font-medium", children: summary.next_meeting.title }), _jsx("div", { className: "text-xs text-zinc-400 mt-0.5", children: new Date(summary.next_meeting.start_at).toLocaleString() })] })), summary.highlights.length > 0 && (_jsxs("div", { className: "mt-3", children: [_jsx("div", { className: "text-xs text-zinc-400 mb-1", children: "Highlights" }), _jsx("ul", { className: "space-y-1 text-sm", children: summary.highlights.map((h, i) => (_jsxs("li", { className: "bg-zinc-800 rounded px-3 py-2", children: [_jsx("div", { className: "font-mono text-xs", children: h.key }), _jsx("div", { className: "text-xs text-zinc-400 mt-0.5", children: typeof h.value === "string"
                                            ? h.value
                                            : JSON.stringify(h.value) })] }, i))) })] }))] }) }));
}

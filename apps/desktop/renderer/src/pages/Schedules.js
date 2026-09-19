import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * Schedules page — master prompt §24 (Scheduler), §25 (Triggers).
 *
 * Lists every scheduled job (workflow + trigger + next_run_at + enabled)
 * with pause / resume / delete buttons. Includes a "New Schedule" form
 * that lets the user pick a workflow, a trigger type, and the trigger
 * config (cron / file pattern / hotkey / webhook URL / system event).
 *
 * A reference panel explains the 8 supported trigger types.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";
export function Schedules() {
    const [jobs, setJobs] = useState([]);
    const [triggers, setTriggers] = useState([]);
    const [workflows, setWorkflows] = useState([]);
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    const [showForm, setShowForm] = useState(false);
    async function refresh() {
        setStatus("loading");
        setError("");
        try {
            const [jobsR, triggersR, wfs] = await Promise.all([
                api.schedules.list(),
                api.schedules.triggers(),
                api.listWorkflows(),
            ]);
            setJobs(jobsR);
            setTriggers(triggersR);
            setWorkflows(wfs);
            setStatus("ready");
        }
        catch (e) {
            setError(String(e));
            setStatus("error");
        }
    }
    useEffect(() => {
        refresh();
    }, []);
    async function handleAction(jobId, action) {
        setError("");
        try {
            if (action === "pause")
                await api.schedules.pause(jobId);
            else if (action === "resume")
                await api.schedules.resume(jobId);
            else
                await api.schedules.remove(jobId);
            await refresh();
        }
        catch (e) {
            setError(String(e));
        }
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Schedules" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Run workflows on a schedule, on file changes, on hotkeys, or via webhooks." })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: () => setShowForm(!showForm), className: "bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm", children: showForm ? "Cancel" : "New Schedule" }), _jsx("button", { onClick: refresh, className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm", children: "Refresh" })] })] }), error && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), showForm && (_jsx(NewScheduleForm, { workflows: workflows, triggers: triggers, onCreated: () => {
                    setShowForm(false);
                    refresh();
                } })), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsxs("div", { className: "px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: ["Scheduled Jobs (", jobs.length, ")"] }), _jsx("div", { className: "divide-y divide-zinc-800", children: status === "loading" ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "Loading..." })) : jobs.length === 0 ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "No scheduled jobs. Click \"New Schedule\" to create one." })) : (jobs.map((job) => (_jsxs("div", { className: "px-4 py-3 flex items-center justify-between gap-4", children: [_jsxs("div", { className: "flex-1 min-w-0", children: [_jsx("div", { className: "text-sm font-medium truncate", children: job.workflow_id ?? "(unknown workflow)" }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5 flex gap-3 flex-wrap", children: [_jsx("span", { className: "text-zinc-400", children: job.trigger_type }), _jsxs("span", { children: ["next: ", job.next_run_time ?? "—"] }), job.is_active !== null && (_jsx("span", { className: job.is_active ? "text-emerald-400" : "text-amber-400", children: job.is_active ? "active" : "paused" }))] }), _jsx("div", { className: "text-xs text-zinc-600 mt-0.5 font-mono truncate", children: job.job_id })] }), _jsxs("div", { className: "flex gap-2", children: [job.is_active && (_jsx("button", { onClick: () => handleAction(job.job_id, "pause"), className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs", children: "Pause" })), !job.is_active && (_jsx("button", { onClick: () => handleAction(job.job_id, "resume"), className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs", children: "Resume" })), _jsx("button", { onClick: () => handleAction(job.job_id, "delete"), className: "bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs", children: "Delete" })] })] }, job.job_id)))) })] }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsxs("div", { className: "px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: ["Trigger Types (", triggers.length, ")"] }), _jsx("div", { className: "grid grid-cols-1 md:grid-cols-2 gap-3 p-4", children: triggers.map((t) => (_jsxs("div", { className: "bg-zinc-950 border border-zinc-800 rounded p-3", children: [_jsx("div", { className: "text-sm font-medium", children: t.type }), _jsx("div", { className: "text-xs text-zinc-400 mt-1", children: t.description }), _jsxs("div", { className: "text-xs text-zinc-500 mt-2", children: ["Required fields:", " ", _jsx("span", { className: "font-mono", children: t.required_fields.join(", ") || "(none)" })] })] }, t.type))) })] })] }));
}
function NewScheduleForm({ workflows, triggers, onCreated, }) {
    const [workflowId, setWorkflowId] = useState(workflows[0]?.id ?? "");
    const [triggerType, setTriggerType] = useState("schedule");
    const [cron, setCron] = useState("0 * * * *");
    const [filePattern, setFilePattern] = useState("*.txt");
    const [hotkey, setHotkey] = useState("ctrl+shift+a");
    const [webhookUrl, setWebhookUrl] = useState("");
    const [systemEvent, setSystemEvent] = useState("startup");
    const [timezone, setTimezone] = useState("UTC");
    const [misfireGrace, setMisfireGrace] = useState(60);
    const [maxConcurrent, setMaxConcurrent] = useState(1);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const triggerConfig = { type: triggerType };
            if (triggerType === "schedule") {
                triggerConfig.schedule_type = "cron";
                triggerConfig.cron = cron;
                triggerConfig.timezone = timezone;
                triggerConfig.misfire_grace_time = misfireGrace;
                triggerConfig.max_concurrent = maxConcurrent;
            }
            else if (triggerType === "file") {
                triggerConfig.file_pattern = filePattern;
            }
            else if (triggerType === "hotkey") {
                triggerConfig.hotkey = hotkey;
            }
            else if (triggerType === "webhook") {
                triggerConfig.webhook_url = webhookUrl;
            }
            else if (triggerType === "system") {
                triggerConfig.event = systemEvent;
            }
            await api.schedules.create({ workflow_id: workflowId, trigger_config: triggerConfig });
            onCreated();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4", children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500", children: "New Schedule" }), _jsxs("div", { className: "grid grid-cols-2 gap-4", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Workflow" }), _jsx("select", { value: workflowId, onChange: (e) => setWorkflowId(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", required: true, children: workflows.length === 0 ? (_jsx("option", { value: "", children: "(no workflows)" })) : (workflows.map((w) => (_jsxs("option", { value: w.id, children: [w.name, " (v", w.version, ")"] }, w.id)))) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Trigger Type" }), _jsxs("select", { value: triggerType, onChange: (e) => setTriggerType(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "schedule", children: "Schedule (cron)" }), _jsx("option", { value: "file", children: "File (file_pattern)" }), _jsx("option", { value: "application", children: "Application (launch/close)" }), _jsx("option", { value: "browser", children: "Browser (url_pattern)" }), _jsx("option", { value: "hotkey", children: "Hotkey (global shortcut)" }), _jsx("option", { value: "webhook", children: "Webhook (POST endpoint)" }), _jsx("option", { value: "system", children: "System (startup/idle)" }), _jsx("option", { value: "manual", children: "Manual (no auto trigger)" })] })] })] }), triggerType === "schedule" && (_jsxs(_Fragment, { children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Cron expression" }), _jsx("input", { value: cron, onChange: (e) => setCron(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm font-mono", placeholder: "0 * * * *", required: true })] }), _jsxs("div", { className: "grid grid-cols-3 gap-4", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Timezone" }), _jsx("input", { value: timezone, onChange: (e) => setTimezone(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Misfire grace (s)" }), _jsx("input", { type: "number", value: misfireGrace, onChange: (e) => setMisfireGrace(Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max concurrent" }), _jsx("input", { type: "number", value: maxConcurrent, onChange: (e) => setMaxConcurrent(Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] })] })] })), triggerType === "file" && (_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "File pattern (glob)" }), _jsx("input", { value: filePattern, onChange: (e) => setFilePattern(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", placeholder: "*.txt", required: true })] })), triggerType === "hotkey" && (_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Hotkey" }), _jsx("input", { value: hotkey, onChange: (e) => setHotkey(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", placeholder: "ctrl+shift+a", required: true })] })), triggerType === "webhook" && (_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Webhook URL (optional)" }), _jsx("input", { value: webhookUrl, onChange: (e) => setWebhookUrl(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", placeholder: "/webhooks/abc-123" }), _jsx("p", { className: "text-xs text-zinc-500 mt-1", children: "A unique URL will be generated if left blank." })] })), triggerType === "system" && (_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "System event" }), _jsxs("select", { value: systemEvent, onChange: (e) => setSystemEvent(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "startup", children: "Startup" }), _jsx("option", { value: "login", children: "Login" }), _jsx("option", { value: "idle", children: "Idle" }), _jsx("option", { value: "network_available", children: "Network available" })] })] })), error && _jsx("div", { className: "text-xs text-red-400", children: error }), _jsx("div", { className: "flex justify-end", children: _jsx("button", { type: "submit", disabled: busy || !workflowId, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Creating..." : "Create Schedule" }) })] }));
}

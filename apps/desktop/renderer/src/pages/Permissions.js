import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Permissions page — master prompt §9 (risk levels), §10 (human confirmation),
 * §55 (security architecture), §88 (rate limits).
 *
 * Three panels:
 * 1. Risk level reference — 4 cards (low / medium / high / critical) with
 *    examples.
 * 2. Granted permissions — list of grants with revoke buttons + a
 *    "Grant Permission" form.
 * 3. Risk policy editor — rate limits (max_actions_per_minute, ...) + per-tool
 *    risk overrides + emergency stop config.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
const COLOR_CLASSES = {
    green: "bg-emerald-500/10 border-emerald-700 text-emerald-300",
    yellow: "bg-yellow-500/10 border-yellow-700 text-yellow-300",
    orange: "bg-orange-500/10 border-orange-700 text-orange-300",
    red: "bg-red-500/10 border-red-700 text-red-300",
};
export function Permissions() {
    const mockMode = useStore((s) => s.mockMode);
    const [levels, setLevels] = useState([]);
    const [grants, setGrants] = useState([]);
    const [tools, setTools] = useState([]);
    const [policy, setPolicy] = useState(null);
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    async function refresh() {
        setStatus("loading");
        setError("");
        try {
            const [lv, gr, ts, pol] = await Promise.all([
                api.permissions.riskLevels(),
                api.permissions.list(),
                api.listTools(),
                api.permissions.getPolicy(),
            ]);
            setLevels(lv.levels);
            setGrants(gr.grants);
            setTools(ts);
            setPolicy(pol);
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
    async function revoke(grantId) {
        if (!window.confirm("Revoke this permission?"))
            return;
        try {
            await api.permissions.revoke(grantId);
            await refresh();
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function savePolicy(next) {
        setError("");
        try {
            await api.permissions.updatePolicy({
                max_actions_per_minute: next.max_actions_per_minute,
                max_ai_calls_per_task: next.max_ai_calls_per_task,
                max_loops: next.max_loops,
                max_file_operations: next.max_file_operations,
                max_browser_tabs: next.max_browser_tabs,
                risk_overrides: next.risk_overrides,
            });
            setPolicy(next);
            setMessage("Policy saved.");
        }
        catch (e) {
            setError(String(e));
        }
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Permissions" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Risk levels, granted permissions, and rate-limit policy." })] }), _jsx("button", { onClick: refresh, className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm", children: "Refresh" })] }), mockMode && (_jsx("div", { className: "bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300", children: "Permission engine is in mock mode \u2014 grants are stored in memory only and lost on service restart." })), error && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), message && (_jsx("div", { className: "bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200", children: message })), _jsxs("div", { children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500 mb-2", children: "Risk Levels" }), _jsx("div", { className: "grid grid-cols-4 gap-3", children: levels.length === 0 ? (_jsx("div", { className: "col-span-4 text-zinc-500 text-sm", children: "Loading..." })) : (levels.map((lv) => (_jsxs("div", { className: `border rounded-lg p-3 ${COLOR_CLASSES[lv.color] ?? "border-zinc-700 text-zinc-300"}`, children: [_jsx("div", { className: "text-sm font-medium uppercase", children: lv.label }), _jsx("div", { className: "text-xs mt-1 opacity-80", children: lv.description }), _jsxs("div", { className: "mt-2 text-xs", children: [_jsx("div", { className: "opacity-60", children: "Examples:" }), _jsx("ul", { className: "mt-0.5 font-mono space-y-0.5", children: lv.examples.map((ex) => (_jsx("li", { children: ex }, ex))) })] })] }, lv.value)))) })] }), _jsxs("div", { className: "grid grid-cols-12 gap-4", children: [_jsxs("div", { className: "col-span-7", children: [_jsx(GrantForm, { tools: tools, levels: levels, onGranted: () => refresh() }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg mt-3", children: [_jsxs("div", { className: "px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: ["Granted Permissions (", grants.length, ")"] }), _jsx("div", { className: "divide-y divide-zinc-800", children: grants.length === 0 ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "No grants. Use the form above to grant one." })) : (grants.map((g) => (_jsxs("div", { className: "px-4 py-2 flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm font-mono", children: g.tool }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5 flex gap-3", children: [_jsxs("span", { children: ["risk: ", g.risk] }), _jsxs("span", { children: ["decision: ", g.decision] }), _jsxs("span", { children: ["profile: ", g.profile_id ?? "global"] })] })] }), _jsx("button", { onClick: () => revoke(g.grant_id), className: "text-xs text-red-400 hover:text-red-300", children: "Revoke" })] }, g.grant_id)))) })] })] }), _jsx("div", { className: "col-span-5", children: policy && (_jsx(PolicyEditor, { policy: policy, onSave: savePolicy })) })] })] }));
}
function GrantForm({ tools, levels, onGranted, }) {
    const [toolName, setToolName] = useState("");
    const [risk, setRisk] = useState("low");
    const [decision, setDecision] = useState("allow_for_workflow");
    const [profileId, setProfileId] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            await api.permissions.grant({
                tool_name: toolName,
                risk_level: risk,
                decision,
                profile_id: profileId || undefined,
            });
            setToolName("");
            onGranted();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3", children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: "Grant Permission" }), _jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Tool" }), _jsxs("select", { value: toolName, onChange: (e) => setToolName(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", required: true, children: [_jsx("option", { value: "", children: "Select a tool..." }), tools.map((t) => (_jsxs("option", { value: t.name, children: [t.name, " (", t.risk_level, ")"] }, t.name)))] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Risk Level" }), _jsxs("select", { value: risk, onChange: (e) => setRisk(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "low", children: "low" }), _jsx("option", { value: "medium", children: "medium" }), _jsx("option", { value: "high", children: "high" }), _jsx("option", { value: "critical", children: "critical" })] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Decision" }), _jsxs("select", { value: decision, onChange: (e) => setDecision(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "allow_once", children: "allow_once" }), _jsx("option", { value: "allow_for_workflow", children: "allow_for_workflow" }), _jsx("option", { value: "always_allow", children: "always_allow" })] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Profile ID (optional)" }), _jsx("input", { value: profileId, onChange: (e) => setProfileId(e.target.value), placeholder: "(global)", className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" })] })] }), error && _jsx("div", { className: "text-xs text-red-400", children: error }), _jsx("div", { className: "flex justify-end", children: _jsx("button", { type: "submit", disabled: busy || !toolName, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Granting..." : "Grant" }) })] }));
}
function PolicyEditor({ policy, onSave, }) {
    const [draft, setDraft] = useState(policy);
    const [overrideTool, setOverrideTool] = useState("");
    const [overrideRisk, setOverrideRisk] = useState("critical");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        setDraft(policy);
    }, [policy]);
    function setField(key, value) {
        setDraft({ ...draft, [key]: value });
    }
    function addOverride() {
        if (!overrideTool)
            return;
        setDraft({
            ...draft,
            risk_overrides: { ...draft.risk_overrides, [overrideTool]: overrideRisk },
        });
        setOverrideTool("");
    }
    function removeOverride(tool) {
        const next = { ...draft.risk_overrides };
        delete next[tool];
        setDraft({ ...draft, risk_overrides: next });
    }
    return (_jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4", children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: "Risk Policy & Rate Limits" }), _jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max actions / minute" }), _jsx("input", { type: "number", value: draft.max_actions_per_minute, onChange: (e) => setField("max_actions_per_minute", Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max AI calls / task" }), _jsx("input", { type: "number", value: draft.max_ai_calls_per_task, onChange: (e) => setField("max_ai_calls_per_task", Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max loops" }), _jsx("input", { type: "number", value: draft.max_loops, onChange: (e) => setField("max_loops", Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max file operations" }), _jsx("input", { type: "number", value: draft.max_file_operations, onChange: (e) => setField("max_file_operations", Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Max browser tabs" }), _jsx("input", { type: "number", value: draft.max_browser_tabs, onChange: (e) => setField("max_browser_tabs", Number(e.target.value)), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", min: 1 })] })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500 mb-2", children: "Per-tool risk overrides" }), _jsx("div", { className: "space-y-1 mb-2", children: Object.entries(draft.risk_overrides).length === 0 ? (_jsx("div", { className: "text-xs text-zinc-600", children: "No overrides." })) : (Object.entries(draft.risk_overrides).map(([tool, risk]) => (_jsxs("div", { className: "flex items-center justify-between bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs", children: [_jsx("span", { className: "font-mono", children: tool }), _jsxs("span", { className: "font-mono text-zinc-400", children: ["\u2192 ", risk] }), _jsx("button", { onClick: () => removeOverride(tool), className: "text-red-400 hover:text-red-300", children: "x" })] }, tool)))) }), _jsxs("div", { className: "flex gap-2", children: [_jsx("input", { value: overrideTool, onChange: (e) => setOverrideTool(e.target.value), placeholder: "tool name e.g. file.delete", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsxs("select", { value: overrideRisk, onChange: (e) => setOverrideRisk(e.target.value), className: "bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "low", children: "low" }), _jsx("option", { value: "medium", children: "medium" }), _jsx("option", { value: "high", children: "high" }), _jsx("option", { value: "critical", children: "critical" })] }), _jsx("button", { onClick: addOverride, disabled: !overrideTool, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: "Add" })] })] }), _jsx("div", { className: "flex justify-end", children: _jsx("button", { onClick: () => {
                        setBusy(true);
                        onSave(draft);
                        setBusy(false);
                    }, disabled: busy, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm", children: busy ? "Saving..." : "Save Policy" }) })] }));
}

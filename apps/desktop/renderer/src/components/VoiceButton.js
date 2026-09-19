import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * VoiceButton — master prompt section 46 (Voice Control).
 *
 * Floating voice control button (bottom-right corner). Implements the
 * voice pipeline:
 *
 *     Microphone -> Speech-to-Text -> AI Planner -> Permission Engine
 *               -> Automation Engine
 *
 * CRITICAL INVARIANT (section 46): voice commands NEVER bypass the
 * security confirmation flow. The "Approve & Run" button is the only
 * way to execute a plan; even if the user said "delete all files",
 * the plan is still surfaced for explicit approval.
 */
import { useState } from "react";
import { Mic, Settings as SettingsIcon, X, Loader2, ShieldAlert, Play } from "lucide-react";
import { api } from "../lib/api";
import { useStore } from "../store";
export function VoiceButton() {
    const [phase, setPhase] = useState("idle");
    const [result, setResult] = useState(null);
    const [runId, setRunId] = useState(null);
    const [error, setError] = useState(null);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const setView = useStore((s) => s.setView);
    async function handleStartListening() {
        setPhase("listening");
        setError(null);
        setResult(null);
        setRunId(null);
        try {
            // Pipeline step 1-3: STT + AI Planner. NO execution.
            setPhase("planning");
            const r = await api.voice.listenAndPlan();
            setResult({ transcript: r.transcript, plan: r.plan });
            setPhase("ready");
        }
        catch (e) {
            setError(e?.message || "Voice listen-and-plan failed");
            setPhase("error");
        }
    }
    async function handleApproveAndRun() {
        if (!result)
            return;
        setPhase("executing");
        setError(null);
        try {
            const r = await api.voice.listenAndExecute(result.plan);
            setRunId(r.run_id);
            setPhase("done");
        }
        catch (e) {
            setError(e?.message || "Plan execution failed");
            setPhase("error");
        }
    }
    function handleCancel() {
        setResult(null);
        setRunId(null);
        setError(null);
        setPhase("idle");
    }
    function openSettings() {
        setSettingsOpen(true);
    }
    function goToVoiceSettings() {
        setSettingsOpen(false);
        setView("voice-settings");
    }
    const listening = phase === "listening" || phase === "planning";
    const busy = phase === "executing";
    return (_jsxs(_Fragment, { children: [_jsxs("div", { className: "fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2", children: [_jsx("button", { onClick: openSettings, title: "Voice settings", className: "w-9 h-9 rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-300 flex items-center justify-center shadow-lg", children: _jsx(SettingsIcon, { size: 16 }) }), _jsx("button", { onClick: handleStartListening, disabled: listening || busy, title: listening ? "Listening..." : "Click to speak", className: `w-14 h-14 rounded-full border flex items-center justify-center shadow-xl transition-all ${listening
                            ? "bg-red-600 border-red-400 animate-pulse"
                            : "bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"} ${busy ? "opacity-50 cursor-not-allowed" : ""}`, children: listening ? (_jsx(Mic, { size: 22, className: "text-white" })) : (_jsx(Mic, { size: 22 })) }), listening && (_jsx("div", { className: "text-xs text-zinc-400 bg-zinc-900/80 px-2 py-1 rounded border border-zinc-800", children: "Listening..." }))] }), phase === "ready" && result && (_jsx("div", { className: "fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4", onClick: handleCancel, children: _jsxs("div", { className: "w-full max-w-2xl bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden", onClick: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "flex items-center justify-between px-5 py-3 border-b border-zinc-800", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx(Mic, { size: 16, className: "text-blue-400" }), _jsx("span", { className: "text-sm font-medium text-zinc-100", children: "Voice command review" })] }), _jsx("button", { onClick: handleCancel, className: "text-zinc-400 hover:text-white", children: _jsx(X, { size: 18 }) })] }), _jsxs("div", { className: "p-5 space-y-4 max-h-[70vh] overflow-y-auto", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: "You said" }), _jsxs("div", { className: "text-sm text-zinc-100 italic bg-zinc-950/50 border border-zinc-800 rounded px-3 py-2", children: ["\"", result.transcript, "\""] })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500 mb-1", children: "AI plan" }), _jsxs("div", { className: "text-sm text-zinc-200 mb-2", children: ["Goal: ", _jsx("span", { className: "text-zinc-100", children: result.plan.goal })] }), _jsxs("div", { className: "flex flex-wrap gap-2 text-xs mb-3", children: [_jsx(RiskBadge, { level: result.plan.overall_risk }), _jsxs("span", { className: "px-2 py-0.5 rounded bg-zinc-800 text-zinc-300", children: [result.plan.steps.length, " steps"] }), _jsxs("span", { className: "px-2 py-0.5 rounded bg-zinc-800 text-zinc-300", children: ["~", result.plan.estimated_duration_seconds, "s"] })] }), _jsx("ol", { className: "space-y-2", children: result.plan.steps.map((step, i) => (_jsxs("li", { className: "text-xs flex items-start gap-2 bg-zinc-950/40 border border-zinc-800 rounded px-3 py-2", children: [_jsxs("span", { className: "text-zinc-500 mt-0.5", children: [i + 1, "."] }), _jsxs("div", { className: "flex-1", children: [_jsx("div", { className: "font-mono text-zinc-200", children: step.action }), _jsxs("div", { className: "text-zinc-500 mt-0.5", children: ["args: ", JSON.stringify(step.args)] })] }), _jsx(RiskBadge, { level: step.risk_level, small: true })] }, step.id))) }), result.plan.potential_side_effects?.length > 0 && (_jsxs("div", { className: "mt-3 text-xs text-amber-300 bg-amber-950/30 border border-amber-800 rounded px-3 py-2", children: ["Side effects: ", result.plan.potential_side_effects.join(", ")] }))] }), _jsxs("div", { className: "flex items-start gap-2 text-xs text-amber-200 bg-amber-950/30 border border-amber-800 rounded px-3 py-2", children: [_jsx(ShieldAlert, { size: 14, className: "mt-0.5 flex-shrink-0" }), _jsxs("div", { children: [_jsx("strong", { children: "Security confirmation required." }), " Voice commands never bypass the permission engine. Review the plan above and click \"Approve & Run\" to execute \u2014 or \"Cancel\" to discard."] })] })] }), _jsxs("div", { className: "flex items-center justify-end gap-2 px-5 py-3 border-t border-zinc-800 bg-zinc-950/40", children: [_jsx("button", { onClick: handleCancel, className: "px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300", children: "Cancel" }), _jsxs("button", { onClick: handleApproveAndRun, className: "px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1.5", children: [_jsx(Play, { size: 14 }), "Approve & Run"] })] })] }) })), phase === "executing" && (_jsx("div", { className: "fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4", children: _jsxs("div", { className: "bg-zinc-900 border border-zinc-700 rounded-lg px-6 py-5 flex items-center gap-3", children: [_jsx(Loader2, { size: 20, className: "animate-spin text-blue-400" }), _jsx("span", { className: "text-sm text-zinc-200", children: "Executing approved plan..." })] }) })), phase === "done" && (_jsxs("div", { className: "fixed bottom-24 right-6 z-50 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl px-4 py-3 max-w-sm", children: [_jsxs("div", { className: "flex items-start justify-between gap-3 mb-1", children: [_jsx("span", { className: "text-sm font-medium text-green-400", children: "Plan launched" }), _jsx("button", { onClick: handleCancel, className: "text-zinc-400 hover:text-white", children: _jsx(X, { size: 14 }) })] }), _jsxs("div", { className: "text-xs text-zinc-400", children: ["Run ID: ", _jsx("span", { className: "font-mono text-zinc-300", children: runId })] })] })), phase === "error" && error && (_jsxs("div", { className: "fixed bottom-24 right-6 z-50 bg-red-950/90 border border-red-700 rounded-lg shadow-xl px-4 py-3 max-w-sm", children: [_jsxs("div", { className: "flex items-start justify-between gap-3 mb-1", children: [_jsx("span", { className: "text-sm font-medium text-red-200", children: "Voice error" }), _jsx("button", { onClick: handleCancel, className: "text-red-300 hover:text-white", children: _jsx(X, { size: 14 }) })] }), _jsx("div", { className: "text-xs text-red-300", children: error })] })), settingsOpen && (_jsx("div", { className: "fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4", onClick: () => setSettingsOpen(false), children: _jsxs("div", { className: "w-full max-w-md bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden", onClick: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "flex items-center justify-between px-5 py-3 border-b border-zinc-800", children: [_jsx("span", { className: "text-sm font-medium text-zinc-100", children: "Voice settings" }), _jsx("button", { onClick: () => setSettingsOpen(false), className: "text-zinc-400 hover:text-white", children: _jsx(X, { size: 18 }) })] }), _jsxs("div", { className: "p-5 space-y-4", children: [_jsx("p", { className: "text-xs text-zinc-400", children: "Open the full voice settings page to configure wake word, voice, continuous listening, and run a TTS test." }), _jsxs("button", { onClick: goToVoiceSettings, className: "w-full px-4 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 flex items-center justify-center gap-2", children: [_jsx(SettingsIcon, { size: 14 }), "Open Voice Settings page"] })] }), _jsx("div", { className: "px-5 py-3 border-t border-zinc-800 bg-zinc-950/40", children: _jsxs("div", { className: "flex items-start gap-2 text-xs text-amber-200", children: [_jsx(ShieldAlert, { size: 14, className: "mt-0.5 flex-shrink-0" }), _jsx("span", { children: "Voice commands require approval \u2014 security confirmation cannot be bypassed." })] }) })] }) }))] }));
}
function RiskBadge({ level, small }) {
    const colors = {
        low: "bg-green-900/60 text-green-300 border-green-800",
        medium: "bg-yellow-900/60 text-yellow-300 border-yellow-800",
        high: "bg-orange-900/60 text-orange-300 border-orange-800",
        critical: "bg-red-900/60 text-red-300 border-red-800",
    };
    const cls = colors[level] || "bg-zinc-800 text-zinc-300 border-zinc-700";
    return (_jsx("span", { className: `inline-flex items-center px-1.5 py-0.5 rounded border text-xs uppercase tracking-wider ${cls} ${small ? "text-[10px]" : ""}`, children: level }));
}

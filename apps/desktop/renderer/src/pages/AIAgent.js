import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** AI Agent chat screen — master prompt §32. */
import { useState } from "react";
import { api } from "../lib/api";
import { LiveComputerView } from "../components/LiveComputerView";
export function AIAgent() {
    const [input, setInput] = useState("");
    const [messages, setMessages] = useState([
        { role: "ai", content: "Hi! Describe what you'd like me to automate. Try something like:\n\n\"Open Chrome, search for AI automation, take a screenshot of the first result, and save it to my Desktop.\"" },
    ]);
    const [loading, setLoading] = useState(false);
    const [showLiveView, setShowLiveView] = useState(true);
    const [liveCompact, setLiveCompact] = useState(false);
    const [taskRunning, setTaskRunning] = useState(false);
    async function send() {
        if (!input.trim() || loading)
            return;
        const userMsg = input;
        setInput("");
        setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
        setLoading(true);
        try {
            const plan = await api.createPlan(userMsg);
            setMessages((prev) => [
                ...prev,
                {
                    role: "ai",
                    content: `Plan generated (${plan.steps.length} steps, risk: ${plan.overall_risk}, est. ${plan.estimated_duration_seconds}s)`,
                    plan,
                },
            ]);
        }
        catch (err) {
            setMessages((prev) => [
                ...prev,
                { role: "ai", content: `Error: ${err.message}` },
            ]);
        }
        finally {
            setLoading(false);
        }
    }
    async function runPlan(plan) {
        setTaskRunning(true);
        try {
            const result = await api.runPlan(plan);
            setMessages((prev) => [
                ...prev,
                { role: "ai", content: `Started run: ${result.run_id}` },
            ]);
        }
        catch (err) {
            setMessages((prev) => [
                ...prev,
                { role: "ai", content: `Failed to start: ${err.message}` },
            ]);
        }
        finally {
            setTaskRunning(false);
        }
    }
    return (_jsxs("div", { className: "flex h-full", children: [_jsxs("div", { className: "flex flex-col flex-1 min-w-0", children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsx("h1", { className: "text-2xl font-semibold", children: "AI Agent" }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsxs("label", { className: "text-xs text-zinc-400 flex items-center gap-1", children: [_jsx("input", { type: "checkbox", checked: liveCompact, onChange: (e) => setLiveCompact(e.target.checked), className: "accent-emerald-500" }), "Compact"] }), _jsx("button", { onClick: () => setShowLiveView((v) => !v), className: "text-xs bg-zinc-800 hover:bg-zinc-700 px-2 py-1 rounded", children: showLiveView ? "Hide Live View" : "Show Live View" })] })] }), _jsxs("div", { className: "flex-1 overflow-auto space-y-3", children: [messages.map((msg, i) => (_jsxs("div", { className: `p-3 rounded-lg max-w-3xl ${msg.role === "user"
                                    ? "bg-blue-900 ml-auto"
                                    : "bg-zinc-800 mr-auto"}`, children: [_jsx("div", { className: "text-xs uppercase text-zinc-400 mb-1", children: msg.role }), _jsx("div", { className: "text-sm whitespace-pre-wrap", children: msg.content }), msg.plan && (_jsxs("div", { className: "mt-3 bg-zinc-900 rounded p-3 border border-zinc-700", children: [_jsx("div", { className: "text-xs text-zinc-400 mb-2", children: "Proposed Plan:" }), _jsx("ol", { className: "text-sm space-y-1", children: msg.plan.steps.map((s) => (_jsxs("li", { children: [_jsxs("span", { className: "text-zinc-500", children: ["#", s.id] }), " ", _jsx("span", { className: "font-mono text-xs bg-zinc-700 px-1 rounded", children: s.action }), "  ", _jsxs("span", { className: `text-xs ${s.risk_level === "critical" ? "text-red-400" :
                                                                s.risk_level === "high" ? "text-amber-400" :
                                                                    s.risk_level === "medium" ? "text-yellow-400" :
                                                                        "text-emerald-400"}`, children: ["[", s.risk_level, "]"] })] }, s.id))) }), _jsx("button", { onClick: () => runPlan(msg.plan), className: "mt-3 bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 rounded text-xs font-medium", children: "Run Plan" })] }))] }, i))), loading && (_jsx("div", { className: "text-zinc-500 text-sm animate-pulse", children: "Thinking..." }))] }), _jsxs("div", { className: "mt-3 flex gap-2", children: [_jsx("input", { type: "text", value: input, onChange: (e) => setInput(e.target.value), onKeyDown: (e) => e.key === "Enter" && send(), placeholder: "Ask AI to automate something...", className: "flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500" }), _jsx("button", { onClick: send, disabled: loading, className: "bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium", children: "Send" })] })] }), showLiveView && (_jsx("aside", { className: "w-80 shrink-0 border-l border-zinc-800", children: _jsx(LiveComputerView, { compact: liveCompact || !taskRunning }) }))] }));
}

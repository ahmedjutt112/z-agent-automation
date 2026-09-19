import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Handle, Position } from "reactflow";
import { Play, Square, MousePointerClick, GitBranch, Repeat, Bell, Sparkles, CircleDot, CheckCircle2, Loader2, AlertTriangle, } from "lucide-react";
// ---------------------------------------------------------------------------
// Status badge — shared by every node kind
// ---------------------------------------------------------------------------
function StatusBadge({ status }) {
    switch (status) {
        case "running":
            return (_jsxs("span", { className: "inline-flex items-center gap-1 text-[10px] text-blue-300", children: [_jsx(Loader2, { size: 11, className: "animate-spin" }), " running"] }));
        case "completed":
            return (_jsxs("span", { className: "inline-flex items-center gap-1 text-[10px] text-emerald-300", children: [_jsx(CheckCircle2, { size: 11 }), " done"] }));
        case "failed":
            return (_jsxs("span", { className: "inline-flex items-center gap-1 text-[10px] text-red-300", children: [_jsx(AlertTriangle, { size: 11 }), " failed"] }));
        default:
            return (_jsxs("span", { className: "inline-flex items-center gap-1 text-[10px] text-zinc-500", children: [_jsx(CircleDot, { size: 11 }), " idle"] }));
    }
}
function NodeShell({ data, icon: Icon, headerClass, borderClass, diamond = false, parallelogram = false, hideSourceHandle = false, hideTargetHandle = false, }) {
    const status = data.status ?? "idle";
    const selected = data.selected ?? false;
    const shapeClass = diamond
        ? "rounded-md transform rotate-45 w-32 h-32 flex items-center justify-center"
        : parallelogram
            ? "transform -skew-x-12"
            : "rounded-md";
    // For diamond shapes we render the content inside a counter-rotated wrapper
    // so the text stays upright.
    const innerWrapper = diamond ? "transform -rotate-45" : "";
    return (_jsxs("div", { className: [
            "relative border bg-zinc-900/95 shadow-md",
            borderClass,
            selected ? "ring-2 ring-blue-500" : "",
            shapeClass,
        ].join(" "), style: { minWidth: diamond ? undefined : 200 }, children: [!hideTargetHandle && (_jsx(Handle, { type: "target", position: Position.Top, className: "!w-2.5 !h-2.5 !bg-zinc-500 !border-zinc-700" })), _jsxs("div", { className: diamond ? innerWrapper + " px-3 py-2" : "px-3 py-2", children: [_jsxs("div", { className: [
                            "flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] font-medium",
                            headerClass,
                        ].join(" "), children: [_jsx(Icon, { size: 12 }), _jsx("span", { className: "truncate", children: data.label })] }), _jsx("div", { className: "mt-1.5 px-1 text-[11px] font-mono text-zinc-300 truncate", children: data.toolName }), data.argsSummary && (_jsx("div", { className: "mt-0.5 px-1 text-[10px] font-mono text-zinc-500 truncate", children: data.argsSummary })), _jsx("div", { className: "mt-1.5 px-1", children: _jsx(StatusBadge, { status: status }) })] }), !hideSourceHandle && (_jsx(Handle, { type: "source", position: Position.Bottom, className: "!w-2.5 !h-2.5 !bg-zinc-500 !border-zinc-700" }))] }));
}
// ---------------------------------------------------------------------------
// Concrete node renderers
// ---------------------------------------------------------------------------
export function StartNode({ data }) {
    return (_jsxs("div", { className: [
            "relative flex items-center justify-center",
            "w-16 h-16 rounded-full bg-emerald-600/20 border-2 border-emerald-500 text-emerald-300",
            data.selected ? "ring-2 ring-emerald-400" : "",
        ].join(" "), children: [_jsx(Handle, { type: "source", position: Position.Bottom, className: "!w-3 !h-3 !bg-emerald-400 !border-emerald-700" }), _jsxs("div", { className: "flex flex-col items-center", children: [_jsx(Play, { size: 18 }), _jsx("span", { className: "text-[10px] mt-0.5 font-medium", children: "Start" })] })] }));
}
export function EndNode({ data }) {
    return (_jsxs("div", { className: [
            "relative flex items-center justify-center",
            "w-16 h-16 rounded-full bg-red-600/20 border-2 border-red-500 text-red-300",
            data.selected ? "ring-2 ring-red-400" : "",
        ].join(" "), children: [_jsx(Handle, { type: "target", position: Position.Top, className: "!w-3 !h-3 !bg-red-400 !border-red-700" }), _jsxs("div", { className: "flex flex-col items-center", children: [_jsx(Square, { size: 18 }), _jsx("span", { className: "text-[10px] mt-0.5 font-medium", children: "End" })] })] }));
}
export function ActionNode({ data }) {
    return (_jsx(NodeShell, { data: data, icon: MousePointerClick, headerClass: "bg-blue-600/30 text-blue-200", borderClass: "border-blue-700/60" }));
}
export function ConditionNode({ data }) {
    return (_jsx(NodeShell, { data: data, icon: GitBranch, headerClass: "bg-yellow-500/30 text-yellow-200", borderClass: "border-yellow-500/60", diamond: true }));
}
export function LoopNode({ data }) {
    return (_jsx(NodeShell, { data: data, icon: Repeat, headerClass: "bg-purple-600/30 text-purple-200", borderClass: "border-purple-600/60", parallelogram: true }));
}
export function NotificationNode({ data }) {
    return (_jsx(NodeShell, { data: data, icon: Bell, headerClass: "bg-orange-600/30 text-orange-200", borderClass: "border-orange-600/60" }));
}
export function AIDecisionNode({ data }) {
    return (_jsxs("div", { className: [
            "relative border bg-gradient-to-br from-blue-900/60 to-purple-900/60 rounded-md shadow-md",
            "border-purple-500/60",
            data.selected ? "ring-2 ring-purple-400" : "",
        ].join(" "), style: { minWidth: 200 }, children: [_jsx(Handle, { type: "target", position: Position.Top, className: "!w-2.5 !h-2.5 !bg-purple-400 !border-purple-700" }), _jsxs("div", { className: "px-3 py-2", children: [_jsxs("div", { className: "flex items-center gap-1.5 px-1 py-0.5 rounded text-[11px] font-medium bg-purple-500/30 text-purple-100", children: [_jsx(Sparkles, { size: 12 }), _jsx("span", { className: "truncate", children: data.label })] }), _jsx("div", { className: "mt-1.5 px-1 text-[11px] font-mono text-zinc-200 truncate", children: data.toolName }), data.argsSummary && (_jsx("div", { className: "mt-0.5 px-1 text-[10px] font-mono text-zinc-400 truncate", children: data.argsSummary })), _jsx("div", { className: "mt-1.5 px-1", children: _jsx(StatusBadge, { status: data.status ?? "idle" }) })] }), _jsx(Handle, { type: "source", position: Position.Bottom, className: "!w-2.5 !h-2.5 !bg-purple-400 !border-purple-700" })] }));
}
// ---------------------------------------------------------------------------
// Registry — used by React Flow's `nodeTypes` prop
// ---------------------------------------------------------------------------
export const workflowNodeTypes = {
    start: StartNode,
    end: EndNode,
    action: ActionNode,
    condition: ConditionNode,
    loop: LoopNode,
    notification: NotificationNode,
    ai_decision: AIDecisionNode,
};
/** Render the right component for a given visual type key. */
export function renderNodeByVisualType(visualType, data) {
    switch (visualType) {
        case "start":
            return _jsx(StartNode, { data: data });
        case "end":
            return _jsx(EndNode, { data: data });
        case "condition":
            return _jsx(ConditionNode, { data: data });
        case "loop":
            return _jsx(LoopNode, { data: data });
        case "notification":
            return _jsx(NotificationNode, { data: data });
        case "ai_decision":
            return _jsx(AIDecisionNode, { data: data });
        case "action":
        default:
            return _jsx(ActionNode, { data: data });
    }
}

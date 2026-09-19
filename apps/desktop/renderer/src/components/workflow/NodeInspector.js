import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Trash2, AlertTriangle } from "lucide-react";
import { PALETTE_CATEGORIES } from "./NodePalette";
const COMMON_FIELDS = {
    "browser.open": [{ key: "browser", label: "Browser", type: "text", placeholder: "chrome" }],
    "browser.navigate": [{ key: "url", label: "URL", type: "text", placeholder: "https://..." }],
    "browser.click": [{ key: "selector", label: "Selector", type: "text", placeholder: "button.submit" }],
    "browser.type": [
        { key: "selector", label: "Selector", type: "text" },
        { key: "text", label: "Text", type: "text" },
    ],
    "browser.extract": [
        { key: "selector", label: "Selector", type: "text" },
        { key: "fields", label: "Fields (comma-separated)", type: "text" },
    ],
    "browser.download": [{ key: "url", label: "URL", type: "text" }],
    "app.launch": [{ key: "path", label: "Executable path", type: "text" }],
    "app.close": [{ key: "name", label: "Process name", type: "text" }],
    "mouse.click": [
        { key: "x", label: "X", type: "number" },
        { key: "y", label: "Y", type: "number" },
    ],
    "keyboard.type": [{ key: "text", label: "Text", type: "textarea" }],
    "keyboard.hotkey": [{ key: "keys", label: "Keys (comma-separated)", type: "text", placeholder: "ctrl,c" }],
    "wait": [{ key: "seconds", label: "Seconds", type: "number" }],
    "screen.capture": [],
    "screen.ocr": [{ key: "region", label: "Region", type: "text", placeholder: "full or x,y,w,h" }],
    "vision.find_image": [{ key: "image_path", label: "Image path", type: "text" }],
    "vision.find_text": [{ key: "text", label: "Search text", type: "text" }],
    "file.read": [{ key: "path", label: "Path", type: "text" }],
    "file.write": [
        { key: "path", label: "Path", type: "text" },
        { key: "content", label: "Content", type: "textarea" },
    ],
    "file.move": [
        { key: "src", label: "Source", type: "text" },
        { key: "dst", label: "Destination", type: "text" },
    ],
    "file.rename": [
        { key: "path", label: "Path", type: "text" },
        { key: "new_name", label: "New name", type: "text" },
    ],
    "file.copy": [
        { key: "src", label: "Source", type: "text" },
        { key: "dst", label: "Destination", type: "text" },
    ],
    "if": [{ key: "condition", label: "Condition (JSON)", type: "textarea" }],
    "for_each": [
        { key: "loop", label: "Loop spec (JSON)", type: "textarea" },
        { key: "action", label: "Inner action", type: "text" },
    ],
    "while": [{ key: "loop", label: "Loop spec (JSON)", type: "textarea" }],
    "wait_until": [{ key: "timeout_ms", label: "Timeout (ms)", type: "number" }],
    "retry": [{ key: "attempts", label: "Attempts", type: "number" }],
    "error_handler": [{ key: "on_error_action", label: "On error", type: "text" }],
    "ai.decision": [
        { key: "prompt", label: "Prompt", type: "textarea" },
        { key: "provider", label: "Provider", type: "text", placeholder: "openai" },
    ],
    "ai.ask_user": [{ key: "prompt", label: "Prompt", type: "textarea" }],
    "approval.request": [{ key: "summary", label: "Summary", type: "textarea" }],
    "code.run_command": [{ key: "command", label: "Command", type: "textarea" }],
    "code.run_python": [{ key: "script", label: "Python script", type: "textarea" }],
    "notify.email": [
        { key: "to", label: "To", type: "text" },
        { key: "subject", label: "Subject", type: "text" },
        { key: "body", label: "Body", type: "textarea" },
    ],
    "notify.webhook": [
        { key: "url", label: "URL", type: "text" },
        { key: "method", label: "Method", type: "text" },
    ],
    "start": [],
    "end": [],
};
function fieldsFor(toolName) {
    return COMMON_FIELDS[toolName] ?? [];
}
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function readArg(value, type) {
    if (value === null || value === undefined)
        return "";
    if (type === "textarea") {
        return typeof value === "string"
            ? value
            : JSON.stringify(value, null, 2);
    }
    if (type === "number") {
        return typeof value === "number" ? String(value) : "";
    }
    if (type === "checkbox") {
        return value ? "true" : "false";
    }
    if (Array.isArray(value))
        return value.join(",");
    if (typeof value === "object")
        return JSON.stringify(value);
    return String(value);
}
function writeArg(prev, raw, type) {
    if (type === "number") {
        if (raw === "")
            return 0;
        const n = Number(raw);
        return Number.isFinite(n) ? n : prev;
    }
    if (type === "checkbox")
        return raw === "true";
    if (type === "textarea") {
        // Try to parse JSON for structured fields like condition/loop.
        const trimmed = raw.trim();
        if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
            try {
                return JSON.parse(trimmed);
            }
            catch {
                return raw;
            }
        }
        return raw;
    }
    // For text fields that look like comma-separated lists.
    if (raw.includes(",") && (raw.includes("[") || !raw.includes(" "))) {
        // Heuristic — leave as string; backend can parse.
        return raw;
    }
    return raw;
}
const VISUAL_TYPE_LABELS = {
    start: "Start",
    end: "End",
    action: "Action",
    condition: "Condition",
    loop: "Loop",
    notification: "Notification",
    ai_decision: "AI Decision",
};
export function NodeInspector({ node, onChange, onDelete }) {
    if (!node) {
        return (_jsxs("aside", { className: "w-80 shrink-0 border-l border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-500", children: [_jsx("h2", { className: "text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-2", children: "Inspector" }), _jsx("p", { className: "text-xs", children: "Select a node on the canvas to edit its properties." })] }));
    }
    // Build the list of alternative tool names within the same visual category
    // so the dropdown only allows switching to visually-compatible nodes.
    const sameCategory = PALETTE_CATEGORIES
        .flatMap((c) => c.items)
        .filter((i) => i.visualType === (node.visual_type ?? "action"));
    const typeOptions = Array.from(new Map(sameCategory.map((i) => [i.toolName, i])).values());
    const visualType = node.visual_type ?? "action";
    const fields = fieldsFor(node.type);
    return (_jsxs("aside", { className: "w-80 shrink-0 border-l border-zinc-800 bg-zinc-950/70 overflow-y-auto h-full", children: [_jsx("div", { className: "px-3 py-2 sticky top-0 bg-zinc-950/95 backdrop-blur border-b border-zinc-800 z-10", children: _jsx("h2", { className: "text-xs font-semibold uppercase tracking-wider text-zinc-400", children: "Inspector" }) }), _jsxs("div", { className: "p-3 space-y-3", children: [_jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "Node ID" }), _jsx("input", { type: "text", value: node.id, readOnly: true, className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-500 font-mono" })] }), _jsxs("div", { children: [_jsxs("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: ["Type (", VISUAL_TYPE_LABELS[visualType], ")"] }), _jsx("select", { value: node.type, onChange: (e) => {
                                    const next = e.target.value;
                                    const match = typeOptions.find((o) => o.toolName === next);
                                    onChange({
                                        type: next,
                                        label: match?.label ?? node.label,
                                        args: match?.defaultArgs ?? node.args,
                                    });
                                }, className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200", children: typeOptions.length === 0 ? (_jsx("option", { value: node.type, children: node.type })) : (typeOptions.map((o) => (_jsxs("option", { value: o.toolName, children: [o.label, " (", o.toolName, ")"] }, o.toolName)))) })] }), _jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "Label" }), _jsx("input", { type: "text", value: node.label ?? "", onChange: (e) => onChange({ label: e.target.value }), className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200" })] }), _jsxs("div", { children: [_jsx("div", { className: "text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1", children: "Arguments" }), fields.length === 0 ? (_jsx("p", { className: "text-[11px] text-zinc-500 italic", children: "No arguments for this node type." })) : (_jsx("div", { className: "space-y-2", children: fields.map((f) => {
                                    const raw = readArg(node.args[f.key], f.type);
                                    return (_jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: f.label }), f.type === "textarea" ? (_jsx("textarea", { rows: 4, value: raw, placeholder: f.placeholder, onChange: (e) => {
                                                    const next = { ...node.args };
                                                    next[f.key] = writeArg(next[f.key], e.target.value, f.type);
                                                    onChange({ args: next });
                                                }, className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono" })) : (_jsx("input", { type: f.type === "number" ? "number" : "text", value: raw, placeholder: f.placeholder, onChange: (e) => {
                                                    const next = { ...node.args };
                                                    next[f.key] = writeArg(next[f.key], e.target.value, f.type);
                                                    onChange({ args: next });
                                                }, className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono" }))] }, f.key));
                                }) }))] }), _jsxs("div", { className: "border-t border-zinc-800 pt-3 space-y-2", children: [_jsx("div", { className: "text-[11px] font-semibold uppercase tracking-wider text-zinc-500", children: "Execution" }), _jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "Timeout (ms)" }), _jsx("input", { type: "number", value: node.timeout_ms, onChange: (e) => onChange({ timeout_ms: Number(e.target.value) || 0 }), className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono" })] }), _jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "Retry count" }), _jsx("input", { type: "number", value: node.retry_count, onChange: (e) => onChange({ retry_count: Number(e.target.value) || 0 }), className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono" })] }), _jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "Risk level" }), _jsxs("select", { value: node.risk_level ?? "low", onChange: (e) => onChange({ risk_level: e.target.value }), className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200", children: [_jsx("option", { value: "low", children: "low" }), _jsx("option", { value: "medium", children: "medium" }), _jsx("option", { value: "high", children: "high" }), _jsx("option", { value: "critical", children: "critical" })] })] }), _jsxs("div", { children: [_jsx("label", { className: "block text-[11px] font-medium text-zinc-400 mb-0.5", children: "On error" }), _jsxs("select", { value: node.on_error_action ?? "stop", onChange: (e) => onChange({ on_error_action: e.target.value }), className: "w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200", children: [_jsx("option", { value: "stop", children: "stop" }), _jsx("option", { value: "continue", children: "continue" }), _jsx("option", { value: "jump_to", children: "jump_to" }), _jsx("option", { value: "retry", children: "retry" })] }), node.on_error_action === "jump_to" && (_jsx("input", { type: "text", value: node.on_error ?? "", placeholder: "target node id", onChange: (e) => onChange({ on_error: e.target.value }), className: "mt-1 w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 font-mono" }))] })] }), _jsx("div", { className: "border-t border-zinc-800 pt-3", children: _jsxs("button", { type: "button", onClick: () => onDelete(node.id), className: "inline-flex items-center gap-1 text-xs text-red-300 hover:text-red-200 px-2 py-1 rounded border border-red-900 hover:bg-red-950/50", children: [_jsx(Trash2, { size: 12 }), " Delete node"] }) }), _jsxs("div", { className: "text-[10px] text-zinc-600 flex items-start gap-1 pt-2 border-t border-zinc-800", children: [_jsx(AlertTriangle, { size: 10, className: "mt-0.5 shrink-0" }), _jsx("span", { children: "Extra args not shown above can be edited by exporting the workflow JSON. Visual metadata (position, label) is preserved automatically." })] })] })] }));
}

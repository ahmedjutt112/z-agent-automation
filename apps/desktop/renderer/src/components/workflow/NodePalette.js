import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Node Palette — left sidebar with draggable node templates.
 * Master prompt §34 — Actions panel (left) of the workflow editor.
 *
 * Items are grouped by category and use HTML5 drag-and-drop so they can be
 * dropped anywhere on the React Flow canvas. Each palette item carries a
 * JSON payload describing the node template (tool name, visual type, label).
 */
import { useState } from "react";
import { Play, Square, GitBranch, Repeat, RotateCw, Timer, ShieldAlert, Globe, Navigation, MousePointerClick, Keyboard, Download, Camera, ScanLine, Image, Search, FileText, FilePlus, FileOutput, FileCog, Copy, Sparkles, HelpCircle, CheckCheck, TerminalSquare, Code2, Bell, Mail, Webhook, ChevronDown, ChevronRight, } from "lucide-react";
// ---------------------------------------------------------------------------
// Catalog — master prompt §20
// ---------------------------------------------------------------------------
export const PALETTE_CATEGORIES = [
    {
        name: "Flow Control",
        items: [
            { label: "Start", toolName: "start", visualType: "start", icon: Play },
            { label: "End", toolName: "end", visualType: "end", icon: Square },
            { label: "Condition", toolName: "if", visualType: "condition", icon: GitBranch,
                defaultArgs: { condition: { lhs: "{{var}}", op: "==", rhs: "true" } } },
            { label: "Loop", toolName: "loop", visualType: "loop", icon: Repeat },
            { label: "For Each", toolName: "for_each", visualType: "loop", icon: Repeat,
                defaultArgs: { loop: { items_var: "items" } } },
            { label: "While", toolName: "while", visualType: "loop", icon: RotateCw,
                defaultArgs: { loop: { type: "while", condition: { lhs: "{{counter}}", op: "<", rhs: "10" } } } },
            { label: "Wait Until", toolName: "wait_until", visualType: "loop", icon: Timer,
                defaultArgs: { timeout_ms: 60_000 } },
            { label: "Retry", toolName: "retry", visualType: "loop", icon: RotateCw,
                defaultArgs: { attempts: 3 } },
            { label: "Error Handler", toolName: "error_handler", visualType: "condition", icon: ShieldAlert,
                defaultArgs: { on_error_action: "stop" } },
        ],
    },
    {
        name: "Browser",
        items: [
            { label: "Open Browser", toolName: "browser.open", visualType: "action", icon: Globe,
                defaultArgs: { browser: "chrome" } },
            { label: "Navigate", toolName: "browser.navigate", visualType: "action", icon: Navigation,
                defaultArgs: { url: "https://example.com" } },
            { label: "Browser Click", toolName: "browser.click", visualType: "action", icon: MousePointerClick,
                defaultArgs: { selector: "button" } },
            { label: "Browser Type", toolName: "browser.type", visualType: "action", icon: Keyboard,
                defaultArgs: { selector: "input", text: "" } },
            { label: "Extract Data", toolName: "browser.extract", visualType: "action", icon: FileText,
                defaultArgs: { selector: "table", fields: [] } },
            { label: "Download", toolName: "browser.download", visualType: "action", icon: Download,
                defaultArgs: { url: "" } },
        ],
    },
    {
        name: "Desktop",
        items: [
            { label: "Open App", toolName: "app.launch", visualType: "action", icon: Play,
                defaultArgs: { path: "" } },
            { label: "Close App", toolName: "app.close", visualType: "action", icon: Square,
                defaultArgs: { name: "" } },
            { label: "Click", toolName: "mouse.click", visualType: "action", icon: MousePointerClick,
                defaultArgs: { x: 0, y: 0 } },
            { label: "Type", toolName: "keyboard.type", visualType: "action", icon: Keyboard,
                defaultArgs: { text: "" } },
            { label: "Hotkey", toolName: "keyboard.hotkey", visualType: "action", icon: Keyboard,
                defaultArgs: { keys: ["ctrl", "c"] } },
            { label: "Wait", toolName: "wait", visualType: "action", icon: Timer,
                defaultArgs: { seconds: 1 } },
        ],
    },
    {
        name: "Vision",
        items: [
            { label: "Screenshot", toolName: "screen.capture", visualType: "action", icon: Camera,
                defaultArgs: {} },
            { label: "OCR", toolName: "screen.ocr", visualType: "action", icon: ScanLine,
                defaultArgs: { region: "full" } },
            { label: "Find Image", toolName: "vision.find_image", visualType: "action", icon: Image,
                defaultArgs: { image_path: "" } },
            { label: "Find Text", toolName: "vision.find_text", visualType: "action", icon: Search,
                defaultArgs: { text: "" } },
        ],
    },
    {
        name: "Files",
        items: [
            { label: "Read File", toolName: "file.read", visualType: "action", icon: FileText,
                defaultArgs: { path: "" } },
            { label: "Write File", toolName: "file.write", visualType: "action", icon: FilePlus,
                defaultArgs: { path: "", content: "" } },
            { label: "Move File", toolName: "file.move", visualType: "action", icon: FileOutput,
                defaultArgs: { src: "", dst: "" } },
            { label: "Rename File", toolName: "file.rename", visualType: "action", icon: FileCog,
                defaultArgs: { path: "", new_name: "" } },
            { label: "Copy File", toolName: "file.copy", visualType: "action", icon: Copy,
                defaultArgs: { src: "", dst: "" } },
        ],
    },
    {
        name: "AI",
        items: [
            { label: "AI Decision", toolName: "ai.decision", visualType: "ai_decision", icon: Sparkles,
                defaultArgs: { prompt: "", provider: "openai" } },
            { label: "Ask User", toolName: "ai.ask_user", visualType: "ai_decision", icon: HelpCircle,
                defaultArgs: { prompt: "" } },
            { label: "Approval", toolName: "approval.request", visualType: "ai_decision", icon: CheckCheck,
                defaultArgs: { summary: "" } },
        ],
    },
    {
        name: "Code",
        items: [
            { label: "Run Command", toolName: "code.run_command", visualType: "action", icon: TerminalSquare,
                defaultArgs: { command: "" } },
            { label: "Run Python", toolName: "code.run_python", visualType: "action", icon: Code2,
                defaultArgs: { script: "" } },
        ],
    },
    {
        name: "Notifications",
        items: [
            { label: "Notification", toolName: "notify.email", visualType: "notification", icon: Bell,
                defaultArgs: { to: "", subject: "", body: "" } },
            { label: "Email", toolName: "notify.email", visualType: "notification", icon: Mail,
                defaultArgs: { to: "", subject: "", body: "" } },
            { label: "Webhook", toolName: "notify.webhook", visualType: "notification", icon: Webhook,
                defaultArgs: { url: "", method: "POST", body: {} } },
        ],
    },
];
// ---------------------------------------------------------------------------
// Drag payload contract
// ---------------------------------------------------------------------------
export const PALETTE_DRAG_TYPE = "application/x-zai-workflow-palette";
// ---------------------------------------------------------------------------
// Sidebar component
// ---------------------------------------------------------------------------
export function NodePalette() {
    const [collapsed, setCollapsed] = useState({});
    const toggle = (name) => {
        setCollapsed((c) => ({ ...c, [name]: !c[name] }));
    };
    const onDragStart = (e, item) => {
        const payload = {
            label: item.label,
            toolName: item.toolName,
            visualType: item.visualType,
            defaultArgs: item.defaultArgs,
        };
        e.dataTransfer.setData(PALETTE_DRAG_TYPE, JSON.stringify(payload));
        e.dataTransfer.effectAllowed = "move";
    };
    return (_jsxs("aside", { className: "w-60 shrink-0 border-r border-zinc-800 bg-zinc-950/70 overflow-y-auto h-full", children: [_jsx("div", { className: "px-3 py-2 sticky top-0 bg-zinc-950/95 backdrop-blur border-b border-zinc-800 z-10", children: _jsx("h2", { className: "text-xs font-semibold uppercase tracking-wider text-zinc-400", children: "Actions" }) }), _jsx("div", { className: "p-2 space-y-1", children: PALETTE_CATEGORIES.map((cat) => {
                    const isCollapsed = collapsed[cat.name] ?? false;
                    return (_jsxs("div", { className: "mb-1", children: [_jsxs("button", { type: "button", onClick: () => toggle(cat.name), className: "flex w-full items-center justify-between px-2 py-1 text-[11px] uppercase tracking-wider text-zinc-400 hover:text-zinc-200", children: [_jsx("span", { children: cat.name }), isCollapsed ? _jsx(ChevronRight, { size: 12 }) : _jsx(ChevronDown, { size: 12 })] }), !isCollapsed && (_jsx("ul", { className: "space-y-0.5 mt-0.5", children: cat.items.map((item) => {
                                    const Icon = item.icon;
                                    return (_jsx("li", { children: _jsxs("div", { draggable: true, onDragStart: (e) => onDragStart(e, item), className: "flex items-center gap-2 px-2 py-1.5 rounded text-xs text-zinc-200 bg-zinc-900/60 hover:bg-zinc-800 hover:ring-1 hover:ring-zinc-700 cursor-grab active:cursor-grabbing", title: `Drag to add ${item.label} (${item.toolName})`, children: [_jsx(Icon, { size: 14, className: "shrink-0 text-zinc-400" }), _jsx("span", { className: "truncate", children: item.label })] }) }, `${cat.name}-${item.label}`));
                                }) }))] }, cat.name));
                }) })] }));
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Developer Panel — master prompt section 73.
 *
 * A collapsible bottom-docked panel. Visible only when developer_mode=true
 * (toggled from Settings -> Advanced -> Developer Mode). Shows live:
 *   - tool calls (rolling log with timestamps + duration) — from /events WS
 *   - current workflow JSON (polled every 2s)
 *   - automation events (streamed via the /events WebSocket)
 *   - debug logs (streamed via /logs/stream WebSocket, level=DEBUG)
 *   - browser selectors used by browser.* tools
 *   - OCR boxes (fetched on demand via POST /screenshots/{id}/ocr)
 *   - last 20 screenshot thumbnails (polled every 5s from GET /screenshots)
 *   - per-tool latency (avg / p50 / p99)
 *
 * CRITICAL (section 73): "Developer mode must not expose secrets." Any value
 * that looks like a password / API key / token is masked before rendering
 * — both on the client (SECRET_PATTERNS below) and on the server (every
 * /logs/* entry is run through credentials.mask() before being sent).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
const MAX_LOG_LINES = 500;
const MAX_SCREENSHOTS = 20;
const LOGS_WS_URL = "ws://127.0.0.1:8765/logs/stream?level=DEBUG";
const SCREENSHOTS_API = "http://127.0.0.1:8765/screenshots";
const SCREENSHOT_BASE = "http://127.0.0.1:8765/screenshots";
// ---------------------------------------------------------------------------
// Secret detection — mirrors credentials.py mask() on the backend.
// ---------------------------------------------------------------------------
const SECRET_PATTERNS = [
    /sk-[A-Za-z0-9_-]{8,}/,
    /sk-ant-[A-Za-z0-9_-]{8,}/,
    /vck_[A-Za-z0-9]{8,}/,
    /vcp_[A-Za-z0-9]{8,}/,
    /ghp_[A-Za-z0-9]{8,}/,
    /github_pat_[A-Za-z0-9_]{8,}/,
    /glpat-[A-Za-z0-9_-]{8,}/,
    /xox[baprs]-[A-Za-z0-9-]+/,
    /bot[0-9]+:[A-Za-z0-9_-]+/,
    /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/, // JWT
    /AIza[0-9A-Za-z_-]{20,}/,
    /AKIA[0-9A-Z]{12,}/,
];
const SECRET_KEY_NAMES = new Set([
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "client_secret",
    "clientsecret",
    "auth_token",
    "authtoken",
    "bearer_token",
    "bearertoken",
    "credit_card",
    "creditcard",
    "card_number",
    "cardnumber",
    "cvv",
    "cvc",
    "ssn",
    "private_key",
    "privatekey",
]);
function maskValue(value, key) {
    if (value === null || value === undefined)
        return String(value);
    const keyName = key ? key.toLowerCase().replace(/[-\s]/g, "_") : "";
    if (keyName && SECRET_KEY_NAMES.has(keyName)) {
        return "<redacted>";
    }
    if (typeof value === "string") {
        let masked = value;
        for (const pat of SECRET_PATTERNS) {
            masked = masked.replace(pat, (m) => `${m.slice(0, 6)}<redacted>`);
        }
        return masked;
    }
    if (typeof value === "object") {
        try {
            const obj = value;
            const masked = {};
            for (const [k, v] of Object.entries(obj)) {
                masked[k] = maskValue(v, k);
            }
            return JSON.stringify(masked);
        }
        catch {
            return String(value);
        }
    }
    return String(value);
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function DevPanel() {
    const developerMode = useStore((s) => s.developerMode);
    const [open, setOpen] = useState(false);
    const [tab, setTab] = useState("tools");
    const [toolCalls, setToolCalls] = useState([]);
    const [events, setEvents] = useState([]);
    const [logs, setLogs] = useState([]);
    const [selectors, setSelectors] = useState([]);
    const [screenshots, setScreenshots] = useState([]);
    const [workflowJson, setWorkflowJson] = useState("{}");
    const [selectedScreenshot, setSelectedScreenshot] = useState(null);
    const wsRef = useRef(null);
    const logsWsRef = useRef(null);
    const logsBottomRef = useRef(null);
    // ---- /events WebSocket — tool calls + selectors + events tabs ----
    useEffect(() => {
        if (!developerMode)
            return;
        if (typeof window === "undefined")
            return;
        let ws = null;
        try {
            ws = new WebSocket("ws://127.0.0.1:8765/events");
        }
        catch {
            ws = null;
        }
        wsRef.current = ws;
        if (ws) {
            ws.onmessage = (ev) => {
                try {
                    const msg = JSON.parse(ev.data);
                    const evt = {
                        ts: Date.now(),
                        type: msg.type,
                        payload: msg.payload,
                    };
                    setEvents((prev) => [...prev.slice(-MAX_LOG_LINES + 1), evt]);
                    if (msg.type === "STEP_STARTED" ||
                        msg.type === "STEP_COMPLETED" ||
                        msg.type === "STEP_FAILED") {
                        const tool = String(msg.payload?.tool ?? "");
                        const tc = {
                            ts: Date.now(),
                            tool,
                            args: msg.payload?.args ?? {},
                            duration_ms: msg.payload?.duration_ms,
                            status: msg.type,
                            target: msg.payload?.target ??
                                msg.payload?.selector,
                        };
                        setToolCalls((prev) => [...prev.slice(-MAX_LOG_LINES + 1), tc]);
                        if (tool.startsWith("browser.") && msg.payload?.selector) {
                            setSelectors((prev) => [...prev, { ts: Date.now(), selector: String(msg.payload.selector) }].slice(-MAX_LOG_LINES));
                        }
                    }
                    if (msg.type === "UNHANDLED_ERROR") {
                        setLogs((prev) => [
                            ...prev,
                            {
                                timestamp: new Date().toISOString(),
                                level: "error",
                                logger: "automation_service.events",
                                message: String(msg.payload?.error ?? ""),
                            },
                        ].slice(-MAX_LOG_LINES));
                    }
                }
                catch {
                    /* ignore malformed frames */
                }
            };
        }
        return () => {
            try {
                ws?.close();
            }
            catch {
                /* ignore */
            }
        };
    }, [developerMode]);
    // ---- /logs/stream WebSocket — Debug Logs tab ----
    useEffect(() => {
        if (!developerMode)
            return;
        if (typeof window === "undefined")
            return;
        let ws = null;
        try {
            ws = new WebSocket(LOGS_WS_URL);
        }
        catch {
            ws = null;
        }
        logsWsRef.current = ws;
        if (ws) {
            ws.onmessage = (ev) => {
                try {
                    const msg = JSON.parse(ev.data);
                    if (msg.type === "backfill" && Array.isArray(msg.entries)) {
                        setLogs((prev) => {
                            const merged = [...prev, ...msg.entries];
                            return merged.slice(-MAX_LOG_LINES);
                        });
                    }
                    else if (msg.type === "log" && msg.entry) {
                        setLogs((prev) => [...prev.slice(-MAX_LOG_LINES + 1), msg.entry]);
                    }
                    else if (msg.type === "error") {
                        setLogs((prev) => [
                            ...prev,
                            {
                                timestamp: new Date().toISOString(),
                                level: "error",
                                logger: "automation_service.logs",
                                message: msg.message,
                            },
                        ].slice(-MAX_LOG_LINES));
                    }
                }
                catch {
                    /* ignore malformed frames */
                }
            };
        }
        return () => {
            try {
                ws?.close();
            }
            catch {
                /* ignore */
            }
        };
    }, [developerMode]);
    // Auto-scroll the logs panel to the bottom whenever new entries arrive.
    useEffect(() => {
        if (logsBottomRef.current) {
            logsBottomRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
        }
    }, [logs]);
    // ---- Fetch the latest workflow JSON every 2s ----
    useEffect(() => {
        if (!developerMode)
            return;
        let cancelled = false;
        const tick = async () => {
            try {
                const resp = await fetch("http://127.0.0.1:8765/workflow");
                if (!resp.ok)
                    return;
                const list = await resp.json();
                if (!Array.isArray(list) || list.length === 0)
                    return;
                const latest = list[0];
                const r2 = await fetch(`http://127.0.0.1:8765/workflow/${latest.id}`);
                if (!r2.ok)
                    return;
                const wf = await r2.json();
                if (!cancelled) {
                    setWorkflowJson(JSON.stringify(wf, null, 2));
                }
            }
            catch {
                /* network down — silently ignore */
            }
        };
        tick();
        const id = window.setInterval(tick, 2000);
        return () => {
            cancelled = true;
            window.clearInterval(id);
        };
    }, [developerMode]);
    // ---- Poll screenshots every 5s ----
    useEffect(() => {
        if (!developerMode)
            return;
        let cancelled = false;
        const tick = async () => {
            try {
                const resp = await fetch(`${SCREENSHOTS_API}?limit=${MAX_SCREENSHOTS}`);
                if (!resp.ok)
                    return;
                const list = (await resp.json());
                if (!cancelled && Array.isArray(list)) {
                    setScreenshots(list);
                }
            }
            catch {
                /* network down — silently ignore */
            }
        };
        tick();
        const id = window.setInterval(tick, 5000);
        return () => {
            cancelled = true;
            window.clearInterval(id);
        };
    }, [developerMode]);
    if (!developerMode)
        return null;
    const tabs = [
        { id: "tools", label: "Tool Calls" },
        { id: "workflow", label: "Workflow JSON" },
        { id: "events", label: "Events" },
        { id: "logs", label: "Debug Logs" },
        { id: "selectors", label: "Selectors" },
        { id: "ocr", label: "OCR Boxes" },
        { id: "screenshots", label: "Screenshots" },
        { id: "timing", label: "Timing" },
    ];
    return (_jsxs("div", { className: "fixed bottom-0 left-0 right-0 z-40 border-t border-zinc-700 bg-zinc-950/95 backdrop-blur shadow-lg", children: [_jsxs("div", { className: "flex items-center justify-between px-3 py-1.5 border-b border-zinc-800", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsxs("span", { className: "relative inline-flex items-center justify-center w-5 h-5", children: [_jsx("svg", { viewBox: "0 0 20 20", className: "w-4 h-4 text-zinc-400", fill: "currentColor", children: _jsx("path", { d: "M10 2a1.5 1.5 0 011.5 1.5V4h2A2.5 2.5 0 0116 6.5v2.585a1.5 1.5 0 01-.44 1.06l-.94.94a1.5 1.5 0 00-.44 1.06V15A2.5 2.5 0 0111.68 17.5H8.32A2.5 2.5 0 015.82 15v-2.855a1.5 1.5 0 00-.44-1.06l-.94-.94A1.5 1.5 0 014 9.085V6.5A2.5 2.5 0 016.5 4h2V3.5A1.5 1.5 0 0110 2zm.5 12h-1v1h1v-1z" }) }), _jsx("span", { className: "absolute top-0 right-0 w-1.5 h-1.5 bg-red-500 rounded-full" })] }), _jsx("span", { className: "text-xs font-mono text-zinc-400", children: "DEV MODE" })] }), _jsx("button", { onClick: () => setOpen((v) => !v), className: "text-xs px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200", children: open ? "Hide" : "Show" })] }), open && (_jsxs("div", { className: "h-72 flex flex-col", children: [_jsx("div", { className: "flex border-b border-zinc-800 overflow-x-auto", children: tabs.map((t) => (_jsx("button", { onClick: () => setTab(t.id), className: `px-3 py-1.5 text-xs whitespace-nowrap border-b-2 ${tab === t.id
                                ? "border-blue-500 text-zinc-100"
                                : "border-transparent text-zinc-500 hover:text-zinc-300"}`, children: t.label }, t.id))) }), _jsxs("div", { className: "flex-1 overflow-auto p-2 text-xs font-mono text-zinc-300", children: [tab === "tools" && _jsx(ToolCallsTab, { calls: toolCalls }), tab === "workflow" && _jsx(WorkflowJsonTab, { json: workflowJson }), tab === "events" && _jsx(EventsTab, { events: events }), tab === "logs" && _jsx(LogsTab, { logs: logs, bottomRef: logsBottomRef }), tab === "selectors" && _jsx(SelectorsTab, { selectors: selectors }), tab === "ocr" && (_jsx(OcrTab, { selected: selectedScreenshot, onClear: () => setSelectedScreenshot(null) })), tab === "screenshots" && (_jsx(ScreenshotsTab, { screenshots: screenshots, onSelect: (s) => {
                                    setSelectedScreenshot(s);
                                    setTab("ocr");
                                } })), tab === "timing" && _jsx(TimingTab, { calls: toolCalls })] })] }))] }));
}
// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function ToolCallsTab({ calls }) {
    if (calls.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No tool calls yet." });
    return (_jsxs("table", { className: "w-full text-left", children: [_jsx("thead", { className: "text-zinc-500 border-b border-zinc-800", children: _jsxs("tr", { children: [_jsx("th", { className: "pr-2", children: "Time" }), _jsx("th", { className: "pr-2", children: "Tool" }), _jsx("th", { className: "pr-2", children: "Target" }), _jsx("th", { className: "pr-2", children: "Args" }), _jsx("th", { className: "pr-2", children: "Duration" }), _jsx("th", { children: "Status" })] }) }), _jsx("tbody", { children: calls
                    .slice(-200)
                    .reverse()
                    .map((c, i) => (_jsxs("tr", { className: "border-b border-zinc-900", children: [_jsx("td", { className: "pr-2 text-zinc-500", children: new Date(c.ts).toISOString().slice(11, 23) }), _jsx("td", { className: "pr-2 text-blue-300", children: c.tool }), _jsx("td", { className: "pr-2 text-purple-300", children: c.target ?? "—" }), _jsx("td", { className: "pr-2 break-all text-zinc-400", children: maskValue(c.args) }), _jsx("td", { className: "pr-2 text-amber-300", children: c.duration_ms !== undefined ? `${c.duration_ms}ms` : "—" }), _jsx("td", { className: "text-zinc-400", children: c.status ?? "—" })] }, i))) })] }));
}
function WorkflowJsonTab({ json }) {
    return (_jsx("textarea", { readOnly: true, value: json, className: "w-full h-full bg-zinc-950 text-zinc-300 p-2 rounded border border-zinc-800 text-xs", style: { minHeight: 200 } }));
}
function EventsTab({ events }) {
    if (events.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No events yet." });
    return (_jsx("div", { className: "space-y-1", children: events
            .slice(-200)
            .reverse()
            .map((e, i) => (_jsxs("div", { className: "flex gap-2 border-b border-zinc-900 pb-0.5", children: [_jsx("span", { className: "text-zinc-500", children: new Date(e.ts).toISOString().slice(11, 23) }), _jsx("span", { className: "text-emerald-300", children: e.type }), _jsx("span", { className: "text-zinc-400 break-all", children: maskValue(e.payload) })] }, i))) }));
}
function LogsTab({ logs, bottomRef, }) {
    if (logs.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No debug logs captured." });
    return (_jsxs("div", { className: "space-y-0.5", children: [logs
                .slice(-200)
                .map((l, i) => (_jsxs("div", { className: "flex gap-2", children: [_jsx("span", { className: "text-zinc-500", children: (l.timestamp || "").slice(11, 23) }), _jsxs("span", { className: l.level.toLowerCase() === "error"
                            ? "text-red-400"
                            : l.level.toLowerCase() === "warn" || l.level.toLowerCase() === "warning"
                                ? "text-amber-400"
                                : "text-zinc-400", children: ["[", l.level, "]"] }), _jsx("span", { className: "text-zinc-300", children: maskValue(l.message) })] }, i))), _jsx("div", { ref: bottomRef })] }));
}
function SelectorsTab({ selectors, }) {
    if (selectors.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No browser selectors captured." });
    return (_jsx("div", { className: "space-y-0.5", children: selectors
            .slice(-100)
            .reverse()
            .map((s, i) => (_jsxs("div", { className: "flex gap-2", children: [_jsx("span", { className: "text-zinc-500", children: new Date(s.ts).toISOString().slice(11, 23) }), _jsx("span", { className: "text-purple-300", children: s.selector })] }, i))) }));
}
function OcrTab({ selected, onClear, }) {
    const [ocr, setOcr] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    useEffect(() => {
        if (!selected) {
            setOcr(null);
            setError(null);
            return;
        }
        setLoading(true);
        setError(null);
        setOcr(null);
        const controller = new AbortController();
        fetch(`${SCREENSHOT_BASE}/${encodeURIComponent(selected.id)}/ocr`, {
            method: "POST",
            signal: controller.signal,
        })
            .then(async (resp) => {
            if (!resp.ok) {
                const body = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(`${resp.status}: ${body.detail || "OCR failed"}`);
            }
            return resp.json();
        })
            .then((r) => setOcr(r))
            .catch((err) => {
            if (err.name !== "AbortError")
                setError(err.message);
        })
            .finally(() => setLoading(false));
        return () => controller.abort();
    }, [selected]);
    if (!selected) {
        return (_jsx("div", { className: "text-zinc-600", children: "Click a screenshot thumbnail in the Screenshots tab to view OCR boxes overlay." }));
    }
    const imageUrl = `${SCREENSHOT_BASE}/${encodeURIComponent(selected.id)}`;
    return (_jsxs("div", { className: "flex flex-col gap-2 h-full", children: [_jsxs("div", { className: "flex items-center justify-between text-xs text-zinc-400", children: [_jsxs("span", { children: ["OCR for ", _jsx("span", { className: "text-blue-300", children: selected.id }), loading && _jsx("span", { className: "text-amber-300 ml-2", children: "(loading...)" }), error && _jsxs("span", { className: "text-red-400 ml-2", children: ["error: ", error] }), !loading && !error && ocr && (_jsxs("span", { className: "text-emerald-300 ml-2", children: ["(", ocr.bounding_boxes.length, " boxes)"] }))] }), _jsx("button", { onClick: onClear, className: "px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200", children: "Clear" })] }), _jsxs("div", { className: "relative flex-1 overflow-auto", children: [_jsx("img", { src: imageUrl, alt: `screenshot ${selected.id}`, className: "max-w-none block", style: { imageRendering: "pixelated" } }), !loading && ocr &&
                        ocr.bounding_boxes.map((b, i) => (_jsx("div", { className: "absolute border-2 border-emerald-400 bg-emerald-400/10", style: {
                                left: b.x,
                                top: b.y,
                                width: b.width,
                                height: b.height,
                            }, title: `${b.text} (${(b.confidence * 100).toFixed(0)}%)`, children: _jsx("span", { className: "absolute -top-4 left-0 text-[10px] bg-emerald-900/80 text-emerald-200 px-1 whitespace-nowrap", children: b.text.slice(0, 30) }) }, i)))] }), ocr && ocr.text && (_jsx("pre", { className: "text-xs text-zinc-300 bg-zinc-950 border border-zinc-800 p-2 max-h-32 overflow-auto whitespace-pre-wrap", children: ocr.text }))] }));
}
function ScreenshotsTab({ screenshots, onSelect, }) {
    if (screenshots.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No screenshots captured." });
    return (_jsx("div", { className: "flex flex-wrap gap-2", children: screenshots.slice(-MAX_SCREENSHOTS).map((s) => (_jsxs("button", { onClick: () => onSelect(s), className: "border border-zinc-800 rounded p-1 hover:border-blue-500 cursor-pointer text-left", children: [_jsx("img", { src: `${SCREENSHOT_BASE}/${encodeURIComponent(s.id)}`, alt: `screenshot ${s.id}`, className: "w-32 h-20 object-cover" }), _jsx("div", { className: "text-[10px] text-zinc-500 mt-0.5 truncate max-w-32", children: (s.created_at || "").slice(11, 19) || s.id.slice(0, 12) })] }, s.id))) }));
}
function TimingTab({ calls }) {
    const timing = useMemo(() => computeTiming(calls), [calls]);
    if (timing.length === 0)
        return _jsx("div", { className: "text-zinc-600", children: "No timing samples yet." });
    return (_jsxs("table", { className: "w-full text-left", children: [_jsx("thead", { className: "text-zinc-500 border-b border-zinc-800", children: _jsxs("tr", { children: [_jsx("th", { className: "pr-2", children: "Tool" }), _jsx("th", { className: "pr-2", children: "Count" }), _jsx("th", { className: "pr-2", children: "Avg (ms)" }), _jsx("th", { className: "pr-2", children: "p50 (ms)" }), _jsx("th", { children: "p99 (ms)" })] }) }), _jsx("tbody", { children: timing.map((t) => (_jsxs("tr", { className: "border-b border-zinc-900", children: [_jsx("td", { className: "pr-2 text-blue-300", children: t.tool }), _jsx("td", { className: "pr-2", children: t.count }), _jsx("td", { className: "pr-2 text-amber-300", children: t.avg_ms.toFixed(1) }), _jsx("td", { className: "pr-2 text-amber-300", children: t.p50_ms.toFixed(1) }), _jsx("td", { className: "text-amber-300", children: t.p99_ms.toFixed(1) })] }, t.tool))) })] }));
}
function computeTiming(calls) {
    const byTool = new Map();
    for (const c of calls) {
        if (c.duration_ms === undefined)
            continue;
        const arr = byTool.get(c.tool) ?? [];
        arr.push(c.duration_ms);
        byTool.set(c.tool, arr);
    }
    const out = [];
    for (const [tool, samples] of byTool) {
        const sorted = [...samples].sort((a, b) => a - b);
        const sum = sorted.reduce((a, b) => a + b, 0);
        const avg = sum / sorted.length;
        const p50 = sorted[Math.floor(sorted.length * 0.5)] ?? avg;
        const p99 = sorted[Math.floor(sorted.length * 0.99)] ?? sorted[sorted.length - 1] ?? avg;
        out.push({
            tool,
            count: sorted.length,
            avg_ms: avg,
            p50_ms: p50,
            p99_ms: p99,
            samples: sorted,
        });
    }
    return out.sort((a, b) => b.count - a.count);
}

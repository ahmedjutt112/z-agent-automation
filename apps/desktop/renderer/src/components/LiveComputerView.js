import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * LiveComputerView — master prompt §33 (Live Computer View).
 *
 * Right-hand panel on the AI Agent screen. Polls POST /agent/observe
 * every 2s and renders:
 *   - the current screenshot
 *   - active application name + window title
 *   - current action being performed (best-effort, from ui_elements[0])
 *   - detected target highlighted on the screenshot (bounding box)
 *   - AI reasoning summary — 1-2 sentences ONLY (§33 forbids exposing
 *     chain-of-thought)
 *   - task status
 *   - "Pause observation" button to stop polling
 *   - compact mode (screenshot + status only) vs full mode
 *
 * CRITICAL: never display the AI's chain-of-thought — only a short
 * summary. The backend enforces the same cap on the reasoning field.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
const OBSERVE_POLL_MS = 2000;
export function LiveComputerView({ compact = false, pollMs = OBSERVE_POLL_MS }) {
    const [observation, setObservation] = useState(null);
    const [paused, setPaused] = useState(false);
    const [error, setError] = useState(null);
    const [highlight, setHighlight] = useState(null);
    const timerRef = useRef(null);
    useEffect(() => {
        if (paused)
            return;
        let cancelled = false;
        async function poll() {
            try {
                // POST with empty body — server captures a fresh screenshot in mock mode.
                const obs = await api.agent.observe({});
                if (cancelled)
                    return;
                setObservation(obs);
                setError(null);
                // Highlight the first detected button-ish element so the user
                // can see what the agent would click next.
                const first = obs.ui_elements?.[0];
                if (first && first.bounding_box && (first.bounding_box.width > 0 || first.bounding_box.height > 0)) {
                    setHighlight(first.bounding_box);
                }
                else {
                    setHighlight(null);
                }
            }
            catch (err) {
                if (cancelled)
                    return;
                setError(err.message);
            }
        }
        poll();
        timerRef.current = window.setInterval(poll, pollMs);
        return () => {
            cancelled = true;
            if (timerRef.current)
                window.clearInterval(timerRef.current);
        };
    }, [paused, pollMs]);
    return (_jsxs("div", { className: "flex flex-col h-full bg-zinc-900 border-l border-zinc-800 overflow-hidden", children: [_jsxs("div", { className: "flex items-center justify-between px-3 py-2 border-b border-zinc-800", children: [_jsx("h2", { className: "text-xs uppercase tracking-wide text-zinc-400", children: "Live Computer View" }), _jsx("button", { onClick: () => setPaused((p) => !p), className: `text-xs px-2 py-1 rounded font-medium ${paused
                            ? "bg-emerald-600 hover:bg-emerald-500"
                            : "bg-zinc-700 hover:bg-zinc-600"}`, children: paused ? "Resume" : "Pause" })] }), _jsxs("div", { className: "relative bg-black aspect-video w-full", children: [observation?.screenshot_path ? (_jsx("img", { src: screenshotUrl(observation.screenshot_path), alt: "screen", className: "w-full h-full object-contain" })) : (_jsx("div", { className: "w-full h-full flex items-center justify-center text-zinc-600 text-xs", children: "waiting for screenshot..." })), highlight && (_jsx("div", { className: "absolute border-2 border-emerald-400 bg-emerald-400/10 pointer-events-none", style: {
                            left: `${scalePct(highlight.x, 1920)}%`,
                            top: `${scalePct(highlight.y, 1080)}%`,
                            width: `${scalePct(highlight.width, 1920)}%`,
                            height: `${scalePct(highlight.height, 1080)}%`,
                        } }))] }), _jsxs("div", { className: "px-3 py-2 border-b border-zinc-800 text-xs space-y-1", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("span", { className: `w-2 h-2 rounded-full ${paused ? "bg-amber-400" : "bg-emerald-400 animate-pulse"}` }), _jsx("span", { className: "text-zinc-400", children: paused ? "observation paused" : "observing" })] }), error && (_jsxs("div", { className: "text-red-400 text-[11px]", children: ["error: ", error] }))] }), !compact && (_jsxs("div", { className: "flex-1 overflow-auto px-3 py-2 space-y-3 text-xs", children: [_jsx(DetailRow, { label: "Active app", value: observation?.active_app ?? "—" }), _jsx(DetailRow, { label: "Window", value: observation?.active_window ?? "—" }), _jsx(DetailRow, { label: "Current action", value: observation?.ui_elements?.[0]?.text ?? "(no target yet)" }), _jsxs("div", { children: [_jsx("div", { className: "text-zinc-500 uppercase tracking-wide mb-1", children: "AI summary" }), _jsx("div", { className: "text-zinc-200", children: truncateReasoning(observation?.ai_summary ?? "") })] }), _jsxs("div", { children: [_jsx("div", { className: "text-zinc-500 uppercase tracking-wide mb-1", children: "Detected elements" }), _jsxs("ul", { className: "space-y-1", children: [(observation?.ui_elements ?? []).slice(0, 5).map((el, i) => (_jsxs("li", { className: "flex items-center justify-between", children: [_jsxs("span", { className: "text-zinc-200 truncate", children: [_jsxs("span", { className: "text-zinc-500 mr-1", children: ["[", el.type, "]"] }), el.text || "(empty)"] }), _jsxs("span", { className: "text-zinc-500 ml-2", children: [(el.confidence * 100).toFixed(0), "%"] })] }, i))), (observation?.ui_elements ?? []).length === 0 && (_jsx("li", { className: "text-zinc-500", children: "(none)" }))] })] }), observation?.observed_at && (_jsxs("div", { className: "text-zinc-500 text-[11px]", children: ["updated ", new Date(observation.observed_at).toLocaleTimeString()] }))] }))] }));
}
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function DetailRow({ label, value }) {
    return (_jsxs("div", { className: "flex items-start gap-2", children: [_jsx("span", { className: "text-zinc-500 uppercase tracking-wide w-24 shrink-0", children: label }), _jsx("span", { className: "text-zinc-200 break-words", children: value })] }));
}
/**
 * Convert a screenshot path returned by /agent/observe into a URL the
 * Electron renderer can <img src=>. The automation-service runs on
 * localhost:8765 and serves screenshots via /screenshots/{id}/file —
 * but the path returned here is just a filesystem path, so we fall
 * back to the screenshots listing endpoint. In mock mode (no real
 * screenshot was captured) the path is still a valid string but the
 * <img> will 404; that's expected — the empty state handles it.
 */
function screenshotUrl(path) {
    if (!path)
        return "";
    // Try the screenshots API. In dev (mock mode) this returns 404 —
    // the broken-image icon is shown. In real mode it serves the PNG.
    const filename = path.split("/").pop();
    return `http://127.0.0.1:8765/screenshots/file/${encodeURIComponent(filename || "")}`;
}
/**
 * Convert a pixel coordinate to a percentage of the screen width/height.
 * Assumes 1920x1080 — the mock ScreenCaptureTool creates images of
 * that size. Real screenshots may differ; the overlay is approximate.
 */
function scalePct(px, total) {
    if (!total)
        return 0;
    return Math.max(0, Math.min(100, (px / total) * 100));
}
/**
 * §33: "Do NOT expose hidden chain-of-thought". Hard-cap the rendered
 * reasoning to ~280 chars + ellipsis. The backend already enforces a
 * 300-char cap; this is defense-in-depth in case the backend is
 * misconfigured.
 */
function truncateReasoning(text) {
    if (!text)
        return "(no summary available)";
    if (text.length <= 280)
        return text;
    return text.slice(0, 280).trimEnd() + "...";
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Browser page — master prompt §16 (Playwright), §17 (browser agent).
 *
 * Manages active browser sessions and exposes per-session navigation,
 * click, type, extract, and screenshot controls.
 *
 * In mock mode the underlying Playwright instance is never started —
 * the backend keeps an in-memory registry of session metadata so the
 * UI can render the session list and per-session action panels.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
export function Browser() {
    const mockMode = useStore((s) => s.mockMode);
    const [sessions, setSessions] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [status, setStatus] = useState("loading");
    const [error, setError] = useState("");
    async function refresh() {
        setStatus("loading");
        setError("");
        try {
            const r = await api.browser.listSessions();
            const list = r.sessions ?? [];
            setSessions(list);
            if (list.length > 0 && !selectedId) {
                setSelectedId(list[0].session_id);
            }
            setStatus("ready");
        }
        catch (e) {
            setError(String(e));
            setStatus("error");
        }
    }
    useEffect(() => {
        refresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const selected = sessions.find((s) => s.session_id === selectedId) ?? null;
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Browser" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Drive Playwright browser sessions from the UI." })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx(NewSessionButton, { onCreated: refresh }), _jsx("button", { onClick: refresh, className: "bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm", children: "Refresh" })] })] }), (mockMode || sessions.some((s) => s.mock_mode)) && (_jsx("div", { className: "bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300", children: "Browser is in mock mode \u2014 sessions are simulated, no real Playwright instance is started." })), status === "error" && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), _jsxs("div", { className: "grid grid-cols-12 gap-4", children: [_jsxs("div", { className: "col-span-4 bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsx("div", { className: "px-4 py-3 border-b border-zinc-800", children: _jsxs("h2", { className: "text-sm uppercase tracking-wider text-zinc-500", children: ["Active Sessions (", sessions.length, ")"] }) }), _jsx("div", { className: "divide-y divide-zinc-800", children: sessions.length === 0 ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "No active sessions. Click \"New Session\" to start." })) : (sessions.map((s) => (_jsxs("button", { onClick: () => setSelectedId(s.session_id), className: `w-full text-left px-4 py-3 hover:bg-zinc-800 transition-colors ${s.session_id === selectedId ? "bg-zinc-800" : ""}`, children: [_jsx("div", { className: "text-sm font-medium truncate", children: s.session_id }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5", children: [s.browser, " ", s.headless ? "(headless)" : "", " \u2014 ", s.current_url || "no url"] })] }, s.session_id)))) })] }), _jsx("div", { className: "col-span-8", children: selected ? (_jsx(SessionPanel, { session: selected, onUpdated: refresh, onClose: async () => {
                                await api.browser.closeSession(selected.session_id);
                                setSelectedId(null);
                                refresh();
                            } })) : (_jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-8 text-center text-zinc-500 text-sm", children: "Select a session on the left to control it." })) })] })] }));
}
function NewSessionButton({ onCreated }) {
    const [open, setOpen] = useState(false);
    const [browser, setBrowser] = useState("chromium");
    const [headless, setHeadless] = useState(true);
    const [sessionId, setSessionId] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            await api.browser.createSession({
                browser,
                headless,
                session_id: sessionId || undefined,
            });
            setSessionId("");
            setOpen(false);
            onCreated();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    if (!open) {
        return (_jsx("button", { onClick: () => setOpen(true), className: "bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm", children: "New Session" }));
    }
    return (_jsx("form", { onSubmit: submit, className: "bg-zinc-900 border border-zinc-700 rounded-lg p-4 absolute right-6 mt-2 z-10 w-80 shadow-lg", children: _jsxs("div", { className: "space-y-3", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Browser" }), _jsxs("select", { value: browser, onChange: (e) => setBrowser(e.target.value), className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm", children: [_jsx("option", { value: "chromium", children: "Chromium" }), _jsx("option", { value: "firefox", children: "Firefox" }), _jsx("option", { value: "webkit", children: "WebKit" })] })] }), _jsxs("label", { className: "flex items-center gap-2 text-sm", children: [_jsx("input", { type: "checkbox", checked: headless, onChange: (e) => setHeadless(e.target.checked) }), "Headless"] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-500", children: "Session ID (optional)" }), _jsx("input", { value: sessionId, onChange: (e) => setSessionId(e.target.value), placeholder: "auto-generated", className: "mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" })] }), error && _jsx("div", { className: "text-xs text-red-400", children: error }), _jsxs("div", { className: "flex gap-2 justify-end", children: [_jsx("button", { type: "button", onClick: () => setOpen(false), className: "text-sm text-zinc-400 hover:text-zinc-200", children: "Cancel" }), _jsx("button", { type: "submit", disabled: busy, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: busy ? "Creating..." : "Create" })] })] }) }));
}
function SessionPanel({ session, onUpdated, onClose, }) {
    const [logs, setLogs] = useState([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [navUrl, setNavUrl] = useState("");
    const [clickSelector, setClickSelector] = useState("");
    const [typeSelector, setTypeSelector] = useState("");
    const [typeText, setTypeText] = useState("");
    const [extractSelector, setExtractSelector] = useState("body");
    const [extractedText, setExtractedText] = useState("");
    function log(type, detail, mock = false) {
        setLogs((prev) => [
            ...prev,
            { type, timestamp: new Date().toISOString(), detail, mock_mode: mock },
        ].slice(-100));
    }
    async function handleNavigate(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const r = await api.browser.navigate(session.session_id, navUrl);
            log("navigate", `navigated to ${navUrl} (${r.title ?? "no title"})`, r.mock_mode);
            onUpdated();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleClick(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const r = await api.browser.click(session.session_id, clickSelector);
            log("click", `clicked ${clickSelector}`, r.mock_mode);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleType(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const r = await api.browser.type(session.session_id, typeSelector, typeText);
            log("type", `typed "${typeText}" into ${typeSelector}`, r.mock_mode);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleExtract(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const r = await api.browser.extract(session.session_id, extractSelector);
            setExtractedText(r.text || "");
            log("extract", `extracted ${r.text?.length ?? 0} chars from ${extractSelector}`, r.mock_mode);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleScreenshot() {
        setBusy(true);
        setError("");
        try {
            const r = await api.browser.screenshot(session.session_id);
            log("screenshot", "captured screenshot", r.mock_mode);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: [_jsxs("div", { className: "flex items-center justify-between mb-3", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm font-medium", children: session.session_id }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5", children: [session.browser, " ", session.headless ? "(headless)" : "", " \u2014 created", " ", new Date(session.created_at).toLocaleString()] }), session.current_url && (_jsx("div", { className: "text-xs text-zinc-400 mt-1 font-mono", children: session.current_url }))] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: handleScreenshot, disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-xs", children: "Screenshot" }), _jsx("button", { onClick: onClose, className: "bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs", children: "Close" })] })] }), error && (_jsx("div", { className: "text-xs text-red-400 mb-3", children: error })), _jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("form", { onSubmit: handleNavigate, className: "flex gap-2", children: [_jsx("input", { value: navUrl, onChange: (e) => setNavUrl(e.target.value), placeholder: "https://example.com", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsx("button", { type: "submit", disabled: busy || !navUrl, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: "Go" })] }), _jsxs("form", { onSubmit: handleClick, className: "flex gap-2", children: [_jsx("input", { value: clickSelector, onChange: (e) => setClickSelector(e.target.value), placeholder: "button#submit", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsx("button", { type: "submit", disabled: busy || !clickSelector, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: "Click" })] }), _jsxs("form", { onSubmit: handleType, className: "flex gap-2 col-span-2", children: [_jsx("input", { value: typeSelector, onChange: (e) => setTypeSelector(e.target.value), placeholder: "input#email", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsx("input", { value: typeText, onChange: (e) => setTypeText(e.target.value), placeholder: "text to type", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsx("button", { type: "submit", disabled: busy || !typeSelector || !typeText, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: "Type" })] }), _jsxs("form", { onSubmit: handleExtract, className: "flex gap-2 col-span-2", children: [_jsx("input", { value: extractSelector, onChange: (e) => setExtractSelector(e.target.value), placeholder: "body", className: "flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm" }), _jsx("button", { type: "submit", disabled: busy, className: "bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm", children: "Extract" })] }), extractedText && (_jsx("div", { className: "col-span-2 bg-zinc-950 border border-zinc-800 rounded p-2 text-xs font-mono text-zinc-400 max-h-32 overflow-y-auto", children: extractedText }))] })] }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsx("div", { className: "px-4 py-2 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500", children: "Session Log" }), _jsx("div", { className: "max-h-48 overflow-y-auto font-mono text-xs", children: logs.length === 0 ? (_jsx("div", { className: "px-4 py-4 text-zinc-600", children: "No actions yet." })) : (logs.map((l, i) => (_jsxs("div", { className: "px-4 py-1 border-b border-zinc-800/50", children: [_jsxs("span", { className: "text-zinc-500", children: [l.timestamp.substr(11, 12), " "] }), _jsxs("span", { className: "text-zinc-300", children: [l.type, ": "] }), _jsx("span", { className: "text-zinc-400", children: l.detail }), l.mock_mode && _jsx("span", { className: "text-amber-500", children: " [mock]" })] }, i)))) })] })] }));
}

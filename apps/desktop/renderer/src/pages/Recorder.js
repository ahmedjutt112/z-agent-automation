import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Recorder page — master prompt §22 (Task Recorder), §35 (Recorder UI).
 *
 * Captures raw mouse / keyboard / browser / file events and compiles them
 * into a Workflow. The recorder lifecycle is:
 *
 *   start  -> record_event*  -> pause / resume (optional) -> stop -> to_workflow
 *
 * Big record / pause / stop buttons drive the lifecycle. A live event list
 * shows captured events as they arrive (polls GET /recorder/events while
 * recording). After stop, a "Save as Workflow" button calls
 * POST /recorder/to-workflow which returns the compiled Workflow.
 *
 * In mock mode the backend TaskRecorder doesn't actually hook into pynput
 * or watchdog — stop() returns a fake Recording with 3-4 sample events so
 * the workflow-generation pipeline can be exercised without a display
 * server. We surface a "Recorder is in mock mode" notice so the user
 * understands the events are simulated.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
const INITIAL_STATE = {
    recording: false,
    paused: false,
    events_count: 0,
    started_at: null,
    mock_mode: true,
};
export function Recorder() {
    const mockMode = useStore((s) => s.mockMode);
    const [state, setState] = useState(INITIAL_STATE);
    const [events, setEvents] = useState([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    const [workflow, setWorkflow] = useState(null);
    const pollRef = useRef(null);
    async function refreshStatus() {
        try {
            const s = await api.recorder.status();
            setState(s);
        }
        catch (e) {
            setError(String(e));
        }
    }
    useEffect(() => {
        refreshStatus();
    }, []);
    // Poll events while recording.
    useEffect(() => {
        if (state.recording) {
            pollRef.current = window.setInterval(async () => {
                try {
                    const r = await api.recorder.events();
                    setEvents(r.events ?? []);
                }
                catch {
                    /* ignore */
                }
            }, 1000);
        }
        else if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
        }
        return () => {
            if (pollRef.current !== null) {
                window.clearInterval(pollRef.current);
                pollRef.current = null;
            }
        };
    }, [state.recording]);
    async function handleStart() {
        setBusy(true);
        setError("");
        setMessage("");
        setEvents([]);
        setWorkflow(null);
        try {
            const s = await api.recorder.start();
            setState(s);
            setMessage("Recording started.");
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handlePauseResume() {
        setBusy(true);
        setError("");
        try {
            const s = state.paused
                ? await api.recorder.resume()
                : await api.recorder.pause();
            setState(s);
            setMessage(state.paused ? "Recording resumed." : "Recording paused.");
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleStop() {
        setBusy(true);
        setError("");
        try {
            const r = await api.recorder.stop();
            // Fetch the final event list.
            const eventsResp = await api.recorder.events();
            setEvents(eventsResp.events ?? []);
            await refreshStatus();
            setMessage(`Recording stopped. ${eventsResp.count} events captured.`);
            // Don't auto-compile — let the user review first.
            void r;
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleDeleteEvent(index) {
        setBusy(true);
        setError("");
        try {
            await api.recorder.deleteEvent(index);
            const r = await api.recorder.events();
            setEvents(r.events ?? []);
            setMessage(`Deleted event at index ${index}.`);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function handleSaveAsWorkflow() {
        setBusy(true);
        setError("");
        try {
            const name = window.prompt("Name this workflow (leave blank for default):", "Recorded Workflow");
            const r = await api.recorder.toWorkflow(name ?? undefined);
            setWorkflow(r.workflow);
            setMessage(`Saved as workflow with ${r.events_count} source events.`);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    const isRecording = state.recording;
    const isPaused = state.paused;
    const isStopped = !isRecording && !isPaused && events.length > 0;
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Recorder" }), _jsx("p", { className: "text-zinc-400 mt-1", children: "Capture desktop + browser actions and compile them into a reusable Workflow." })] }), (state.mock_mode || mockMode) && (_jsx("div", { className: "bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300", children: "Recorder is in mock mode \u2014 events are simulated." })), error && (_jsx("div", { className: "bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300", children: error })), message && (_jsx("div", { className: "bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200", children: message })), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-6", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-4", children: [_jsxs("button", { onClick: handleStart, disabled: busy || isRecording, className: "flex items-center gap-2 bg-red-700 hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium", title: "Start recording", children: [_jsx("span", { className: "w-4 h-4 rounded-full bg-white inline-block" }), "Record"] }), _jsxs("button", { onClick: handlePauseResume, disabled: busy || (!isRecording && !isPaused), className: "flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium", title: isPaused ? "Resume recording" : "Pause recording", children: [_jsxs("span", { className: "flex gap-0.5", children: [_jsx("span", { className: "w-1 h-4 bg-white inline-block" }), _jsx("span", { className: "w-1 h-4 bg-white inline-block" })] }), isPaused ? "Resume" : "Pause"] }), _jsxs("button", { onClick: handleStop, disabled: busy || (!isRecording && !isPaused), className: "flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium", title: "Stop recording", children: [_jsx("span", { className: "w-4 h-4 bg-white inline-block" }), "Stop"] })] }), _jsxs("div", { className: "text-right", children: [_jsx("div", { className: "text-xs uppercase tracking-wider text-zinc-500", children: "Status" }), _jsx("div", { className: `text-sm font-medium ${isRecording
                                            ? "text-red-400"
                                            : isPaused
                                                ? "text-amber-400"
                                                : "text-zinc-400"}`, children: isRecording ? "Recording..." : isPaused ? "Paused" : "Stopped" }), _jsxs("div", { className: "text-xs text-zinc-500 mt-1", children: [events.length, " event(s)"] })] })] }), state.started_at && (_jsxs("div", { className: "mt-4 text-xs text-zinc-500", children: ["Started at: ", _jsx("span", { className: "font-mono", children: state.started_at })] }))] }), _jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsxs("div", { className: "px-4 py-3 border-b border-zinc-800 flex items-center justify-between", children: [_jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500", children: "Events" }), events.length > 0 && (_jsxs("span", { className: "text-xs text-zinc-500", children: [events.length, " captured"] }))] }), _jsx("div", { className: "divide-y divide-zinc-800 max-h-[400px] overflow-y-auto", children: events.length === 0 ? (_jsx("div", { className: "px-4 py-8 text-center text-zinc-500 text-sm", children: "No events captured yet. Click Record to start." })) : (events.map((ev, i) => (_jsx(EventRow, { event: ev, index: i, onDelete: () => handleDeleteEvent(i) }, `${ev.timestamp}-${i}`)))) })] }), isStopped && (_jsx("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg p-4", children: _jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-sm font-medium", children: "Compile recording into a Workflow" }), _jsx("p", { className: "text-xs text-zinc-500 mt-1", children: "The recorder will merge mouse moves into clicks, join keyboard events into type actions, and emit one node per browser / file event." })] }), _jsx("button", { onClick: handleSaveAsWorkflow, disabled: busy, className: "bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-2 text-sm font-medium", children: busy ? "Saving..." : "Save as Workflow" })] }) })), workflow && (_jsxs("div", { className: "bg-zinc-900 border border-zinc-800 rounded-lg", children: [_jsx("div", { className: "px-4 py-3 border-b border-zinc-800", children: _jsx("h2", { className: "text-sm uppercase tracking-wider text-zinc-500", children: "Compiled Workflow" }) }), _jsx("pre", { className: "px-4 py-3 text-xs font-mono text-zinc-300 overflow-x-auto max-h-[400px]", children: JSON.stringify(workflow, null, 2) })] }))] }));
}
function EventRow({ event, index, onDelete, }) {
    const typeColor = (t) => {
        if (t.startsWith("mouse."))
            return "text-blue-300";
        if (t.startsWith("keyboard."))
            return "text-purple-300";
        if (t.startsWith("browser."))
            return "text-emerald-300";
        if (t.startsWith("file."))
            return "text-amber-300";
        return "text-zinc-300";
    };
    return (_jsxs("div", { className: "px-4 py-3 flex items-center justify-between gap-4", children: [_jsxs("div", { className: "flex-1 min-w-0", children: [_jsxs("div", { className: "flex items-center gap-3 text-xs text-zinc-500", children: [_jsxs("span", { className: "font-mono", children: ["#", index] }), _jsx("span", { className: "font-mono", children: new Date(event.timestamp * 1000).toISOString().substr(11, 12) }), _jsx("span", { className: `font-mono ${typeColor(event.type)}`, children: event.type }), event.target && (_jsxs("span", { className: "font-mono truncate text-zinc-400", children: ["target=", event.target] }))] }), _jsxs("div", { className: "mt-1 text-xs text-zinc-400 font-mono truncate", children: ["args=", JSON.stringify(event.args)] })] }), _jsx("button", { onClick: onDelete, className: "text-xs text-red-400 hover:text-red-300 px-2 py-1", title: "Delete this event", children: "Delete" })] }));
}

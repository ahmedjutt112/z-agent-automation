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

import React, { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

interface RecordedEvent {
  timestamp: number;
  type: string;
  target: string | null;
  args: Record<string, unknown>;
}

interface RecorderState {
  recording: boolean;
  paused: boolean;
  events_count: number;
  started_at: string | null;
  mock_mode: boolean;
}

const INITIAL_STATE: RecorderState = {
  recording: false,
  paused: false,
  events_count: 0,
  started_at: null,
  mock_mode: true,
};

export function Recorder() {
  const mockMode = useStore((s) => s.mockMode);
  const [state, setState] = useState<RecorderState>(INITIAL_STATE);
  const [events, setEvents] = useState<RecordedEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [workflow, setWorkflow] = useState<unknown | null>(null);
  const pollRef = useRef<number | null>(null);

  async function refreshStatus() {
    try {
      const s = await api.recorder.status();
      setState(s as RecorderState);
    } catch (e) {
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
          setEvents((r.events as RecordedEvent[]) ?? []);
        } catch {
          /* ignore */
        }
      }, 1000);
    } else if (pollRef.current !== null) {
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
      setState(s as RecorderState);
      setMessage("Recording started.");
    } catch (e) {
      setError(String(e));
    } finally {
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
      setState(s as RecorderState);
      setMessage(state.paused ? "Recording resumed." : "Recording paused.");
    } catch (e) {
      setError(String(e));
    } finally {
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
      setEvents((eventsResp.events as RecordedEvent[]) ?? []);
      await refreshStatus();
      setMessage(
        `Recording stopped. ${eventsResp.count} events captured.`,
      );
      // Don't auto-compile — let the user review first.
      void r;
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteEvent(index: number) {
    setBusy(true);
    setError("");
    try {
      await api.recorder.deleteEvent(index);
      const r = await api.recorder.events();
      setEvents((r.events as RecordedEvent[]) ?? []);
      setMessage(`Deleted event at index ${index}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveAsWorkflow() {
    setBusy(true);
    setError("");
    try {
      const name = window.prompt(
        "Name this workflow (leave blank for default):",
        "Recorded Workflow",
      );
      const r = await api.recorder.toWorkflow(name ?? undefined);
      setWorkflow(r.workflow);
      setMessage(
        `Saved as workflow with ${r.events_count} source events.`,
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const isRecording = state.recording;
  const isPaused = state.paused;
  const isStopped = !isRecording && !isPaused && events.length > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Recorder</h1>
        <p className="text-zinc-400 mt-1">
          Capture desktop + browser actions and compile them into a reusable Workflow.
        </p>
      </div>

      {(state.mock_mode || mockMode) && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300">
          Recorder is in mock mode — events are simulated.
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {message && (
        <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200">
          {message}
        </div>
      )}

      {/* Controls */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={handleStart}
              disabled={busy || isRecording}
              className="flex items-center gap-2 bg-red-700 hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium"
              title="Start recording"
            >
              <span className="w-4 h-4 rounded-full bg-white inline-block" />
              Record
            </button>
            <button
              onClick={handlePauseResume}
              disabled={busy || (!isRecording && !isPaused)}
              className="flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium"
              title={isPaused ? "Resume recording" : "Pause recording"}
            >
              <span className="flex gap-0.5">
                <span className="w-1 h-4 bg-white inline-block" />
                <span className="w-1 h-4 bg-white inline-block" />
              </span>
              {isPaused ? "Resume" : "Pause"}
            </button>
            <button
              onClick={handleStop}
              disabled={busy || (!isRecording && !isPaused)}
              className="flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg px-5 py-3 font-medium"
              title="Stop recording"
            >
              <span className="w-4 h-4 bg-white inline-block" />
              Stop
            </button>
          </div>
          <div className="text-right">
            <div className="text-xs uppercase tracking-wider text-zinc-500">Status</div>
            <div
              className={`text-sm font-medium ${
                isRecording
                  ? "text-red-400"
                  : isPaused
                  ? "text-amber-400"
                  : "text-zinc-400"
              }`}
            >
              {isRecording ? "Recording..." : isPaused ? "Paused" : "Stopped"}
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              {events.length} event(s)
            </div>
          </div>
        </div>
        {state.started_at && (
          <div className="mt-4 text-xs text-zinc-500">
            Started at: <span className="font-mono">{state.started_at}</span>
          </div>
        )}
      </div>

      {/* Live event list */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-wider text-zinc-500">Events</h2>
          {events.length > 0 && (
            <span className="text-xs text-zinc-500">{events.length} captured</span>
          )}
        </div>
        <div className="divide-y divide-zinc-800 max-h-[400px] overflow-y-auto">
          {events.length === 0 ? (
            <div className="px-4 py-8 text-center text-zinc-500 text-sm">
              No events captured yet. Click Record to start.
            </div>
          ) : (
            events.map((ev, i) => (
              <EventRow
                key={`${ev.timestamp}-${i}`}
                event={ev}
                index={i}
                onDelete={() => handleDeleteEvent(i)}
              />
            ))
          )}
        </div>
      </div>

      {/* Save as workflow */}
      {isStopped && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium">Compile recording into a Workflow</h2>
              <p className="text-xs text-zinc-500 mt-1">
                The recorder will merge mouse moves into clicks, join keyboard
                events into type actions, and emit one node per browser / file event.
              </p>
            </div>
            <button
              onClick={handleSaveAsWorkflow}
              disabled={busy}
              className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-2 text-sm font-medium"
            >
              {busy ? "Saving..." : "Save as Workflow"}
            </button>
          </div>
        </div>
      )}

      {/* Compiled workflow preview */}
      {workflow && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
          <div className="px-4 py-3 border-b border-zinc-800">
            <h2 className="text-sm uppercase tracking-wider text-zinc-500">
              Compiled Workflow
            </h2>
          </div>
          <pre className="px-4 py-3 text-xs font-mono text-zinc-300 overflow-x-auto max-h-[400px]">
            {JSON.stringify(workflow, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function EventRow({
  event,
  index,
  onDelete,
}: {
  event: RecordedEvent;
  index: number;
  onDelete: () => void;
}) {
  const typeColor = (t: string) => {
    if (t.startsWith("mouse.")) return "text-blue-300";
    if (t.startsWith("keyboard.")) return "text-purple-300";
    if (t.startsWith("browser.")) return "text-emerald-300";
    if (t.startsWith("file.")) return "text-amber-300";
    return "text-zinc-300";
  };
  return (
    <div className="px-4 py-3 flex items-center justify-between gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <span className="font-mono">#{index}</span>
          <span className="font-mono">
            {new Date(event.timestamp * 1000).toISOString().substr(11, 12)}
          </span>
          <span className={`font-mono ${typeColor(event.type)}`}>{event.type}</span>
          {event.target && (
            <span className="font-mono truncate text-zinc-400">
              target={event.target}
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-zinc-400 font-mono truncate">
          args={JSON.stringify(event.args)}
        </div>
      </div>
      <button
        onClick={onDelete}
        className="text-xs text-red-400 hover:text-red-300 px-2 py-1"
        title="Delete this event"
      >
        Delete
      </button>
    </div>
  );
}

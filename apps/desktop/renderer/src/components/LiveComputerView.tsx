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

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface UIElement {
  text: string;
  type: string;
  bounding_box: BoundingBox;
  confidence: number;
}

export interface Observation {
  screenshot_path: string;
  active_app: string | null;
  active_window: string | null;
  ui_elements: UIElement[];
  text_on_screen: string[];
  ai_summary: string;
  observed_at: string;
}

interface Props {
  /** When false, only render the screenshot + status row. */
  compact?: boolean;
  /** Override the poll interval (mainly for tests). */
  pollMs?: number;
}

export function LiveComputerView({ compact = false, pollMs = OBSERVE_POLL_MS }: Props) {
  const [observation, setObservation] = useState<Observation | null>(null);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<BoundingBox | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (paused) return;

    let cancelled = false;

    async function poll() {
      try {
        // POST with empty body — server captures a fresh screenshot in mock mode.
        const obs = await api.agent.observe({});
        if (cancelled) return;
        setObservation(obs);
        setError(null);
        // Highlight the first detected button-ish element so the user
        // can see what the agent would click next.
        const first = obs.ui_elements?.[0];
        if (first && first.bounding_box && (first.bounding_box.width > 0 || first.bounding_box.height > 0)) {
          setHighlight(first.bounding_box);
        } else {
          setHighlight(null);
        }
      } catch (err) {
        if (cancelled) return;
        setError((err as Error).message);
      }
    }

    poll();
    timerRef.current = window.setInterval(poll, pollMs);

    return () => {
      cancelled = true;
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [paused, pollMs]);

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-l border-zinc-800 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <h2 className="text-xs uppercase tracking-wide text-zinc-400">
          Live Computer View
        </h2>
        <button
          onClick={() => setPaused((p) => !p)}
          className={`text-xs px-2 py-1 rounded font-medium ${
            paused
              ? "bg-emerald-600 hover:bg-emerald-500"
              : "bg-zinc-700 hover:bg-zinc-600"
          }`}
        >
          {paused ? "Resume" : "Pause"}
        </button>
      </div>

      {/* Screenshot + bounding box overlay */}
      <div className="relative bg-black aspect-video w-full">
        {observation?.screenshot_path ? (
          <img
            src={screenshotUrl(observation.screenshot_path)}
            alt="screen"
            className="w-full h-full object-contain"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-600 text-xs">
            waiting for screenshot...
          </div>
        )}
        {highlight && (
          <div
            className="absolute border-2 border-emerald-400 bg-emerald-400/10 pointer-events-none"
            style={{
              left: `${scalePct(highlight.x, 1920)}%`,
              top: `${scalePct(highlight.y, 1080)}%`,
              width: `${scalePct(highlight.width, 1920)}%`,
              height: `${scalePct(highlight.height, 1080)}%`,
            }}
          />
        )}
      </div>

      {/* Status row */}
      <div className="px-3 py-2 border-b border-zinc-800 text-xs space-y-1">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${paused ? "bg-amber-400" : "bg-emerald-400 animate-pulse"}`} />
          <span className="text-zinc-400">
            {paused ? "observation paused" : "observing"}
          </span>
        </div>
        {error && (
          <div className="text-red-400 text-[11px]">error: {error}</div>
        )}
      </div>

      {/* Detail rows — hidden in compact mode */}
      {!compact && (
        <div className="flex-1 overflow-auto px-3 py-2 space-y-3 text-xs">
          <DetailRow label="Active app" value={observation?.active_app ?? "—"} />
          <DetailRow label="Window" value={observation?.active_window ?? "—"} />
          <DetailRow
            label="Current action"
            value={observation?.ui_elements?.[0]?.text ?? "(no target yet)"}
          />
          <div>
            <div className="text-zinc-500 uppercase tracking-wide mb-1">AI summary</div>
            {/* §33 — NEVER expose chain-of-thought. The backend already
                caps the reasoning to 1-2 sentences; we further truncate
                the rendered text as a defense-in-depth. */}
            <div className="text-zinc-200">
              {truncateReasoning(observation?.ai_summary ?? "")}
            </div>
          </div>
          <div>
            <div className="text-zinc-500 uppercase tracking-wide mb-1">
              Detected elements
            </div>
            <ul className="space-y-1">
              {(observation?.ui_elements ?? []).slice(0, 5).map((el, i) => (
                <li key={i} className="flex items-center justify-between">
                  <span className="text-zinc-200 truncate">
                    <span className="text-zinc-500 mr-1">[{el.type}]</span>
                    {el.text || "(empty)"}
                  </span>
                  <span className="text-zinc-500 ml-2">
                    {(el.confidence * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
              {(observation?.ui_elements ?? []).length === 0 && (
                <li className="text-zinc-500">(none)</li>
              )}
            </ul>
          </div>
          {observation?.observed_at && (
            <div className="text-zinc-500 text-[11px]">
              updated {new Date(observation.observed_at).toLocaleTimeString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-zinc-500 uppercase tracking-wide w-24 shrink-0">
        {label}
      </span>
      <span className="text-zinc-200 break-words">{value}</span>
    </div>
  );
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
function screenshotUrl(path: string): string {
  if (!path) return "";
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
function scalePct(px: number, total: number): number {
  if (!total) return 0;
  return Math.max(0, Math.min(100, (px / total) * 100));
}

/**
 * §33: "Do NOT expose hidden chain-of-thought". Hard-cap the rendered
 * reasoning to ~280 chars + ellipsis. The backend already enforces a
 * 300-char cap; this is defense-in-depth in case the backend is
 * misconfigured.
 */
function truncateReasoning(text: string): string {
  if (!text) return "(no summary available)";
  if (text.length <= 280) return text;
  return text.slice(0, 280).trimEnd() + "...";
}

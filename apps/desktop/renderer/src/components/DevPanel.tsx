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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";

const MAX_LOG_LINES = 500;
const MAX_SCREENSHOTS = 20;
const LOGS_WS_URL = "ws://127.0.0.1:8765/logs/stream?level=DEBUG";
const SCREENSHOTS_API = "http://127.0.0.1:8765/screenshots";
const SCREENSHOT_BASE = "http://127.0.0.1:8765/screenshots";

type Tab =
  | "tools"
  | "workflow"
  | "events"
  | "logs"
  | "selectors"
  | "ocr"
  | "screenshots"
  | "timing";

interface ToolCall {
  ts: number;
  tool: string;
  args: Record<string, unknown>;
  duration_ms?: number;
  status?: string;
  target?: string;
}

interface AutomationEvent {
  ts: number;
  type: string;
  payload: Record<string, unknown>;
}

interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  tool?: string | null;
  task_id?: string | null;
}

interface ScreenshotMeta {
  id: string;
  task_id?: string | null;
  profile_id?: string | null;
  file_path: string;
  width?: number | null;
  height?: number | null;
  metadata_json?: Record<string, unknown> | null;
  created_at: string;
}

interface OcrBoundingBox {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
}

interface OcrResult {
  text: string;
  bounding_boxes: OcrBoundingBox[];
}

interface TimingEntry {
  tool: string;
  count: number;
  avg_ms: number;
  p50_ms: number;
  p99_ms: number;
  samples: number[];
}

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

function maskValue(value: unknown, key?: string): string {
  if (value === null || value === undefined) return String(value);
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
      const obj = value as Record<string, unknown>;
      const masked: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(obj)) {
        masked[k] = maskValue(v, k);
      }
      return JSON.stringify(masked);
    } catch {
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
  const [tab, setTab] = useState<Tab>("tools");

  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [events, setEvents] = useState<AutomationEvent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [selectors, setSelectors] = useState<{ ts: number; selector: string }[]>([]);
  const [screenshots, setScreenshots] = useState<ScreenshotMeta[]>([]);
  const [workflowJson, setWorkflowJson] = useState<string>("{}");
  const [selectedScreenshot, setSelectedScreenshot] = useState<ScreenshotMeta | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const logsWsRef = useRef<WebSocket | null>(null);
  const logsBottomRef = useRef<HTMLDivElement | null>(null);

  // ---- /events WebSocket — tool calls + selectors + events tabs ----
  useEffect(() => {
    if (!developerMode) return;
    if (typeof window === "undefined") return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket("ws://127.0.0.1:8765/events");
    } catch {
      ws = null;
    }
    wsRef.current = ws;
    if (ws) {
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as { type: string; payload: Record<string, unknown> };
          const evt: AutomationEvent = {
            ts: Date.now(),
            type: msg.type,
            payload: msg.payload,
          };
          setEvents((prev) => [...prev.slice(-MAX_LOG_LINES + 1), evt]);
          if (
            msg.type === "STEP_STARTED" ||
            msg.type === "STEP_COMPLETED" ||
            msg.type === "STEP_FAILED"
          ) {
            const tool = String(msg.payload?.tool ?? "");
            const tc: ToolCall = {
              ts: Date.now(),
              tool,
              args: (msg.payload?.args as Record<string, unknown>) ?? {},
              duration_ms: msg.payload?.duration_ms as number | undefined,
              status: msg.type,
              target:
                (msg.payload?.target as string | undefined) ??
                (msg.payload?.selector as string | undefined),
            };
            setToolCalls((prev) => [...prev.slice(-MAX_LOG_LINES + 1), tc]);
            if (tool.startsWith("browser.") && msg.payload?.selector) {
              setSelectors((prev) =>
                [...prev, { ts: Date.now(), selector: String(msg.payload.selector) }].slice(
                  -MAX_LOG_LINES,
                ),
              );
            }
          }
          if (msg.type === "UNHANDLED_ERROR") {
            setLogs((prev) =>
              [
                ...prev,
                {
                  timestamp: new Date().toISOString(),
                  level: "error",
                  logger: "automation_service.events",
                  message: String(msg.payload?.error ?? ""),
                },
              ].slice(-MAX_LOG_LINES),
            );
          }
        } catch {
          /* ignore malformed frames */
        }
      };
    }
    return () => {
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [developerMode]);

  // ---- /logs/stream WebSocket — Debug Logs tab ----
  useEffect(() => {
    if (!developerMode) return;
    if (typeof window === "undefined") return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(LOGS_WS_URL);
    } catch {
      ws = null;
    }
    logsWsRef.current = ws;
    if (ws) {
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as
            | { type: "backfill"; entries: LogEntry[] }
            | { type: "log"; entry: LogEntry }
            | { type: "heartbeat"; ts: string }
            | { type: "error"; message: string };
          if (msg.type === "backfill" && Array.isArray(msg.entries)) {
            setLogs((prev) => {
              const merged = [...prev, ...msg.entries];
              return merged.slice(-MAX_LOG_LINES);
            });
          } else if (msg.type === "log" && msg.entry) {
            setLogs((prev) => [...prev.slice(-MAX_LOG_LINES + 1), msg.entry]);
          } else if (msg.type === "error") {
            setLogs((prev) =>
              [
                ...prev,
                {
                  timestamp: new Date().toISOString(),
                  level: "error",
                  logger: "automation_service.logs",
                  message: msg.message,
                },
              ].slice(-MAX_LOG_LINES),
            );
          }
        } catch {
          /* ignore malformed frames */
        }
      };
    }
    return () => {
      try {
        ws?.close();
      } catch {
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
    if (!developerMode) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const resp = await fetch("http://127.0.0.1:8765/workflow");
        if (!resp.ok) return;
        const list = await resp.json();
        if (!Array.isArray(list) || list.length === 0) return;
        const latest = list[0];
        const r2 = await fetch(`http://127.0.0.1:8765/workflow/${latest.id}`);
        if (!r2.ok) return;
        const wf = await r2.json();
        if (!cancelled) {
          setWorkflowJson(JSON.stringify(wf, null, 2));
        }
      } catch {
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
    if (!developerMode) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const resp = await fetch(`${SCREENSHOTS_API}?limit=${MAX_SCREENSHOTS}`);
        if (!resp.ok) return;
        const list = (await resp.json()) as ScreenshotMeta[];
        if (!cancelled && Array.isArray(list)) {
          setScreenshots(list);
        }
      } catch {
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

  if (!developerMode) return null;

  const tabs: { id: Tab; label: string }[] = [
    { id: "tools", label: "Tool Calls" },
    { id: "workflow", label: "Workflow JSON" },
    { id: "events", label: "Events" },
    { id: "logs", label: "Debug Logs" },
    { id: "selectors", label: "Selectors" },
    { id: "ocr", label: "OCR Boxes" },
    { id: "screenshots", label: "Screenshots" },
    { id: "timing", label: "Timing" },
  ];

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-zinc-700 bg-zinc-950/95 backdrop-blur shadow-lg">
      {/* Toggle bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <span className="relative inline-flex items-center justify-center w-5 h-5">
            <svg viewBox="0 0 20 20" className="w-4 h-4 text-zinc-400" fill="currentColor">
              <path d="M10 2a1.5 1.5 0 011.5 1.5V4h2A2.5 2.5 0 0116 6.5v2.585a1.5 1.5 0 01-.44 1.06l-.94.94a1.5 1.5 0 00-.44 1.06V15A2.5 2.5 0 0111.68 17.5H8.32A2.5 2.5 0 015.82 15v-2.855a1.5 1.5 0 00-.44-1.06l-.94-.94A1.5 1.5 0 014 9.085V6.5A2.5 2.5 0 016.5 4h2V3.5A1.5 1.5 0 0110 2zm.5 12h-1v1h1v-1z" />
            </svg>
            <span className="absolute top-0 right-0 w-1.5 h-1.5 bg-red-500 rounded-full" />
          </span>
          <span className="text-xs font-mono text-zinc-400">DEV MODE</span>
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-xs px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>

      {open && (
        <div className="h-72 flex flex-col">
          <div className="flex border-b border-zinc-800 overflow-x-auto">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 text-xs whitespace-nowrap border-b-2 ${
                  tab === t.id
                    ? "border-blue-500 text-zinc-100"
                    : "border-transparent text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-auto p-2 text-xs font-mono text-zinc-300">
            {tab === "tools" && <ToolCallsTab calls={toolCalls} />}
            {tab === "workflow" && <WorkflowJsonTab json={workflowJson} />}
            {tab === "events" && <EventsTab events={events} />}
            {tab === "logs" && <LogsTab logs={logs} bottomRef={logsBottomRef} />}
            {tab === "selectors" && <SelectorsTab selectors={selectors} />}
            {tab === "ocr" && (
              <OcrTab
                selected={selectedScreenshot}
                onClear={() => setSelectedScreenshot(null)}
              />
            )}
            {tab === "screenshots" && (
              <ScreenshotsTab
                screenshots={screenshots}
                onSelect={(s) => {
                  setSelectedScreenshot(s);
                  setTab("ocr");
                }}
              />
            )}
            {tab === "timing" && <TimingTab calls={toolCalls} />}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ToolCallsTab({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0)
    return <div className="text-zinc-600">No tool calls yet.</div>;
  return (
    <table className="w-full text-left">
      <thead className="text-zinc-500 border-b border-zinc-800">
        <tr>
          <th className="pr-2">Time</th>
          <th className="pr-2">Tool</th>
          <th className="pr-2">Target</th>
          <th className="pr-2">Args</th>
          <th className="pr-2">Duration</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {calls
          .slice(-200)
          .reverse()
          .map((c, i) => (
            <tr key={i} className="border-b border-zinc-900">
              <td className="pr-2 text-zinc-500">
                {new Date(c.ts).toISOString().slice(11, 23)}
              </td>
              <td className="pr-2 text-blue-300">{c.tool}</td>
              <td className="pr-2 text-purple-300">{c.target ?? "—"}</td>
              <td className="pr-2 break-all text-zinc-400">{maskValue(c.args)}</td>
              <td className="pr-2 text-amber-300">
                {c.duration_ms !== undefined ? `${c.duration_ms}ms` : "—"}
              </td>
              <td className="text-zinc-400">{c.status ?? "—"}</td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}

function WorkflowJsonTab({ json }: { json: string }) {
  return (
    <textarea
      readOnly
      value={json}
      className="w-full h-full bg-zinc-950 text-zinc-300 p-2 rounded border border-zinc-800 text-xs"
      style={{ minHeight: 200 }}
    />
  );
}

function EventsTab({ events }: { events: AutomationEvent[] }) {
  if (events.length === 0)
    return <div className="text-zinc-600">No events yet.</div>;
  return (
    <div className="space-y-1">
      {events
        .slice(-200)
        .reverse()
        .map((e, i) => (
          <div key={i} className="flex gap-2 border-b border-zinc-900 pb-0.5">
            <span className="text-zinc-500">
              {new Date(e.ts).toISOString().slice(11, 23)}
            </span>
            <span className="text-emerald-300">{e.type}</span>
            <span className="text-zinc-400 break-all">{maskValue(e.payload)}</span>
          </div>
        ))}
    </div>
  );
}

function LogsTab({
  logs,
  bottomRef,
}: {
  logs: LogEntry[];
  bottomRef: React.RefObject<HTMLDivElement | null>;
}) {
  if (logs.length === 0)
    return <div className="text-zinc-600">No debug logs captured.</div>;
  return (
    <div className="space-y-0.5">
      {logs
        .slice(-200)
        .map((l, i) => (
          <div key={i} className="flex gap-2">
            <span className="text-zinc-500">
              {(l.timestamp || "").slice(11, 23)}
            </span>
            <span
              className={
                l.level.toLowerCase() === "error"
                  ? "text-red-400"
                  : l.level.toLowerCase() === "warn" || l.level.toLowerCase() === "warning"
                  ? "text-amber-400"
                  : "text-zinc-400"
              }
            >
              [{l.level}]
            </span>
            <span className="text-zinc-300">{maskValue(l.message)}</span>
          </div>
        ))}
      <div ref={bottomRef} />
    </div>
  );
}

function SelectorsTab({
  selectors,
}: {
  selectors: { ts: number; selector: string }[];
}) {
  if (selectors.length === 0)
    return <div className="text-zinc-600">No browser selectors captured.</div>;
  return (
    <div className="space-y-0.5">
      {selectors
        .slice(-100)
        .reverse()
        .map((s, i) => (
          <div key={i} className="flex gap-2">
            <span className="text-zinc-500">
              {new Date(s.ts).toISOString().slice(11, 23)}
            </span>
            <span className="text-purple-300">{s.selector}</span>
          </div>
        ))}
    </div>
  );
}

function OcrTab({
  selected,
  onClear,
}: {
  selected: ScreenshotMeta | null;
  onClear: () => void;
}) {
  const [ocr, setOcr] = useState<OcrResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      .then((r: OcrResult) => setOcr(r))
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [selected]);

  if (!selected) {
    return (
      <div className="text-zinc-600">
        Click a screenshot thumbnail in the Screenshots tab to view OCR boxes
        overlay.
      </div>
    );
  }
  const imageUrl = `${SCREENSHOT_BASE}/${encodeURIComponent(selected.id)}`;
  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex items-center justify-between text-xs text-zinc-400">
        <span>
          OCR for <span className="text-blue-300">{selected.id}</span>
          {loading && <span className="text-amber-300 ml-2">(loading...)</span>}
          {error && <span className="text-red-400 ml-2">error: {error}</span>}
          {!loading && !error && ocr && (
            <span className="text-emerald-300 ml-2">
              ({ocr.bounding_boxes.length} boxes)
            </span>
          )}
        </span>
        <button
          onClick={onClear}
          className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
        >
          Clear
        </button>
      </div>
      <div className="relative flex-1 overflow-auto">
        <img
          src={imageUrl}
          alt={`screenshot ${selected.id}`}
          className="max-w-none block"
          style={{ imageRendering: "pixelated" }}
        />
        {!loading && ocr &&
          ocr.bounding_boxes.map((b, i) => (
            <div
              key={i}
              className="absolute border-2 border-emerald-400 bg-emerald-400/10"
              style={{
                left: b.x,
                top: b.y,
                width: b.width,
                height: b.height,
              }}
              title={`${b.text} (${(b.confidence * 100).toFixed(0)}%)`}
            >
              <span className="absolute -top-4 left-0 text-[10px] bg-emerald-900/80 text-emerald-200 px-1 whitespace-nowrap">
                {b.text.slice(0, 30)}
              </span>
            </div>
          ))}
      </div>
      {ocr && ocr.text && (
        <pre className="text-xs text-zinc-300 bg-zinc-950 border border-zinc-800 p-2 max-h-32 overflow-auto whitespace-pre-wrap">
          {ocr.text}
        </pre>
      )}
    </div>
  );
}

function ScreenshotsTab({
  screenshots,
  onSelect,
}: {
  screenshots: ScreenshotMeta[];
  onSelect: (s: ScreenshotMeta) => void;
}) {
  if (screenshots.length === 0)
    return <div className="text-zinc-600">No screenshots captured.</div>;
  return (
    <div className="flex flex-wrap gap-2">
      {screenshots.slice(-MAX_SCREENSHOTS).map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s)}
          className="border border-zinc-800 rounded p-1 hover:border-blue-500 cursor-pointer text-left"
        >
          <img
            src={`${SCREENSHOT_BASE}/${encodeURIComponent(s.id)}`}
            alt={`screenshot ${s.id}`}
            className="w-32 h-20 object-cover"
          />
          <div className="text-[10px] text-zinc-500 mt-0.5 truncate max-w-32">
            {(s.created_at || "").slice(11, 19) || s.id.slice(0, 12)}
          </div>
        </button>
      ))}
    </div>
  );
}

function TimingTab({ calls }: { calls: ToolCall[] }) {
  const timing = useMemo(() => computeTiming(calls), [calls]);
  if (timing.length === 0)
    return <div className="text-zinc-600">No timing samples yet.</div>;
  return (
    <table className="w-full text-left">
      <thead className="text-zinc-500 border-b border-zinc-800">
        <tr>
          <th className="pr-2">Tool</th>
          <th className="pr-2">Count</th>
          <th className="pr-2">Avg (ms)</th>
          <th className="pr-2">p50 (ms)</th>
          <th>p99 (ms)</th>
        </tr>
      </thead>
      <tbody>
        {timing.map((t) => (
          <tr key={t.tool} className="border-b border-zinc-900">
            <td className="pr-2 text-blue-300">{t.tool}</td>
            <td className="pr-2">{t.count}</td>
            <td className="pr-2 text-amber-300">{t.avg_ms.toFixed(1)}</td>
            <td className="pr-2 text-amber-300">{t.p50_ms.toFixed(1)}</td>
            <td className="text-amber-300">{t.p99_ms.toFixed(1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function computeTiming(calls: ToolCall[]): TimingEntry[] {
  const byTool = new Map<string, number[]>();
  for (const c of calls) {
    if (c.duration_ms === undefined) continue;
    const arr = byTool.get(c.tool) ?? [];
    arr.push(c.duration_ms);
    byTool.set(c.tool, arr);
  }
  const out: TimingEntry[] = [];
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

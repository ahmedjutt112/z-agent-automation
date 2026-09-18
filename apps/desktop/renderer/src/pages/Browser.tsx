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

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

interface BrowserSession {
  session_id: string;
  browser: string;
  headless: boolean;
  created_at: string;
  current_url: string | null;
  title: string | null;
  mock_mode: boolean;
}

interface BrowserLogEntry {
  type: string;
  timestamp: string;
  detail: string;
  mock_mode: boolean;
}

export function Browser() {
  const mockMode = useStore((s) => s.mockMode);
  const [sessions, setSessions] = useState<BrowserSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string>("");

  async function refresh() {
    setStatus("loading");
    setError("");
    try {
      const r = await api.browser.listSessions();
      const list = (r.sessions as BrowserSession[]) ?? [];
      setSessions(list);
      if (list.length > 0 && !selectedId) {
        setSelectedId(list[0].session_id);
      }
      setStatus("ready");
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = sessions.find((s) => s.session_id === selectedId) ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Browser</h1>
          <p className="text-zinc-400 mt-1">
            Drive Playwright browser sessions from the UI.
          </p>
        </div>
        <div className="flex gap-2">
          <NewSessionButton onCreated={refresh} />
          <button
            onClick={refresh}
            className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm"
          >
            Refresh
          </button>
        </div>
      </div>

      {(mockMode || sessions.some((s) => s.mock_mode)) && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300">
          Browser is in mock mode — sessions are simulated, no real Playwright instance is started.
        </div>
      )}

      {status === "error" && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* Session list */}
        <div className="col-span-4 bg-zinc-900 border border-zinc-800 rounded-lg">
          <div className="px-4 py-3 border-b border-zinc-800">
            <h2 className="text-sm uppercase tracking-wider text-zinc-500">
              Active Sessions ({sessions.length})
            </h2>
          </div>
          <div className="divide-y divide-zinc-800">
            {sessions.length === 0 ? (
              <div className="px-4 py-8 text-center text-zinc-500 text-sm">
                No active sessions. Click "New Session" to start.
              </div>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.session_id}
                  onClick={() => setSelectedId(s.session_id)}
                  className={`w-full text-left px-4 py-3 hover:bg-zinc-800 transition-colors ${
                    s.session_id === selectedId ? "bg-zinc-800" : ""
                  }`}
                >
                  <div className="text-sm font-medium truncate">
                    {s.session_id}
                  </div>
                  <div className="text-xs text-zinc-500 mt-0.5">
                    {s.browser} {s.headless ? "(headless)" : ""} — {s.current_url || "no url"}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Session detail */}
        <div className="col-span-8">
          {selected ? (
            <SessionPanel
              session={selected}
              onUpdated={refresh}
              onClose={async () => {
                await api.browser.closeSession(selected.session_id);
                setSelectedId(null);
                refresh();
              }}
            />
          ) : (
            <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-8 text-center text-zinc-500 text-sm">
              Select a session on the left to control it.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NewSessionButton({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [browser, setBrowser] = useState("chromium");
  const [headless, setHeadless] = useState(true);
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
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
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm"
      >
        New Session
      </button>
    );
  }
  return (
    <form
      onSubmit={submit}
      className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 absolute right-6 mt-2 z-10 w-80 shadow-lg"
    >
      <div className="space-y-3">
        <div>
          <label className="text-xs text-zinc-500">Browser</label>
          <select
            value={browser}
            onChange={(e) => setBrowser(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="chromium">Chromium</option>
            <option value="firefox">Firefox</option>
            <option value="webkit">WebKit</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={headless}
            onChange={(e) => setHeadless(e.target.checked)}
          />
          Headless
        </label>
        <div>
          <label className="text-xs text-zinc-500">Session ID (optional)</label>
          <input
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            placeholder="auto-generated"
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          />
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-sm text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
          >
            {busy ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </form>
  );
}

function SessionPanel({
  session,
  onUpdated,
  onClose,
}: {
  session: BrowserSession;
  onUpdated: () => void;
  onClose: () => void;
}) {
  const [logs, setLogs] = useState<BrowserLogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [navUrl, setNavUrl] = useState("");
  const [clickSelector, setClickSelector] = useState("");
  const [typeSelector, setTypeSelector] = useState("");
  const [typeText, setTypeText] = useState("");
  const [extractSelector, setExtractSelector] = useState("body");
  const [extractedText, setExtractedText] = useState("");

  function log(type: string, detail: string, mock = false) {
    setLogs((prev) =>
      [
        ...prev,
        { type, timestamp: new Date().toISOString(), detail, mock_mode: mock },
      ].slice(-100),
    );
  }

  async function handleNavigate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.browser.navigate(session.session_id, navUrl);
      log("navigate", `navigated to ${navUrl} (${r.title ?? "no title"})`, r.mock_mode);
      onUpdated();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleClick(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.browser.click(session.session_id, clickSelector);
      log("click", `clicked ${clickSelector}`, r.mock_mode);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleType(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.browser.type(session.session_id, typeSelector, typeText);
      log("type", `typed "${typeText}" into ${typeSelector}`, r.mock_mode);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleExtract(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.browser.extract(session.session_id, extractSelector);
      setExtractedText(r.text || "");
      log("extract", `extracted ${r.text?.length ?? 0} chars from ${extractSelector}`, r.mock_mode);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleScreenshot() {
    setBusy(true);
    setError("");
    try {
      const r = await api.browser.screenshot(session.session_id);
      log("screenshot", "captured screenshot", r.mock_mode);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-medium">{session.session_id}</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              {session.browser} {session.headless ? "(headless)" : ""} — created{" "}
              {new Date(session.created_at).toLocaleString()}
            </div>
            {session.current_url && (
              <div className="text-xs text-zinc-400 mt-1 font-mono">
                {session.current_url}
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleScreenshot}
              disabled={busy}
              className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-xs"
            >
              Screenshot
            </button>
            <button
              onClick={onClose}
              className="bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs"
            >
              Close
            </button>
          </div>
        </div>

        {error && (
          <div className="text-xs text-red-400 mb-3">{error}</div>
        )}

        <div className="grid grid-cols-2 gap-3">
          {/* Navigate */}
          <form onSubmit={handleNavigate} className="flex gap-2">
            <input
              value={navUrl}
              onChange={(e) => setNavUrl(e.target.value)}
              placeholder="https://example.com"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            />
            <button
              type="submit"
              disabled={busy || !navUrl}
              className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
            >
              Go
            </button>
          </form>

          {/* Click */}
          <form onSubmit={handleClick} className="flex gap-2">
            <input
              value={clickSelector}
              onChange={(e) => setClickSelector(e.target.value)}
              placeholder="button#submit"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            />
            <button
              type="submit"
              disabled={busy || !clickSelector}
              className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
            >
              Click
            </button>
          </form>

          {/* Type */}
          <form onSubmit={handleType} className="flex gap-2 col-span-2">
            <input
              value={typeSelector}
              onChange={(e) => setTypeSelector(e.target.value)}
              placeholder="input#email"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            />
            <input
              value={typeText}
              onChange={(e) => setTypeText(e.target.value)}
              placeholder="text to type"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            />
            <button
              type="submit"
              disabled={busy || !typeSelector || !typeText}
              className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
            >
              Type
            </button>
          </form>

          {/* Extract */}
          <form onSubmit={handleExtract} className="flex gap-2 col-span-2">
            <input
              value={extractSelector}
              onChange={(e) => setExtractSelector(e.target.value)}
              placeholder="body"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            />
            <button
              type="submit"
              disabled={busy}
              className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
            >
              Extract
            </button>
          </form>

          {extractedText && (
            <div className="col-span-2 bg-zinc-950 border border-zinc-800 rounded p-2 text-xs font-mono text-zinc-400 max-h-32 overflow-y-auto">
              {extractedText}
            </div>
          )}
        </div>
      </div>

      {/* Session log */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
        <div className="px-4 py-2 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
          Session Log
        </div>
        <div className="max-h-48 overflow-y-auto font-mono text-xs">
          {logs.length === 0 ? (
            <div className="px-4 py-4 text-zinc-600">No actions yet.</div>
          ) : (
            logs.map((l, i) => (
              <div key={i} className="px-4 py-1 border-b border-zinc-800/50">
                <span className="text-zinc-500">{l.timestamp.substr(11, 12)} </span>
                <span className="text-zinc-300">{l.type}: </span>
                <span className="text-zinc-400">{l.detail}</span>
                {l.mock_mode && <span className="text-amber-500"> [mock]</span>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * AI Assistant page — master prompt §83 (Phase 5 — Advanced AI OS Assistant).
 *
 * Distinct from the AIAgent chat page: this one exposes high-level
 * contextual automation goals ("prepare for my next meeting", "morning
 * routine", "research a topic", "organise files by context", "end-of-day
 * summary") + a calendar peek.
 *
 * CRITICAL (§83): every external action must still pass through permissions
 * and user-defined policies. Every plan-returning endpoint returns
 * executed=false; the user must click "Approve & Run" before the plan is
 * sent to /assistant/run-meeting-prep (or /task/run).
 *
 * Master prompt §85: the top of the page has a 3-way mode selector
 * (Assist / Guided / Autonomous) that toggles how aggressive the assistant
 * is allowed to be.
 */

import { useCallback, useEffect, useState } from "react";
import { api, CalendarEvent, Plan } from "../lib/api";

type AssistantMode = "assist" | "guided" | "autonomous";

interface PlanModalState {
  plan: Plan;
  source: string; // human-readable label for the modal title
  // Optional meeting / dashboard context for the prepare-meeting flow.
  meeting?: CalendarEvent | null;
  dashboardUrl?: string | null;
  openedApps?: string[];
  openedTabs?: string[];
}

interface SummaryModalState {
  date: string;
  total_runs: number;
  total_tasks: number;
  highlights: Array<{ key: string; value: unknown; at: string }>;
  task_context: Array<{ key: string; value: unknown; at: string }>;
  next_meeting?: {
    title: string;
    start_at: string;
    meeting_link?: string | null;
  } | null;
  mock_mode?: boolean;
}

export function Assistant() {
  const [mode, setMode] = useState<AssistantMode>("guided");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planModal, setPlanModal] = useState<PlanModalState | null>(null);
  const [summaryModal, setSummaryModal] = useState<SummaryModalState | null>(null);

  // Calendar — next 5 events, polled every 60s.
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [calendarProvider, setCalendarProvider] = useState<string>("");

  const refreshCalendar = useCallback(async () => {
    try {
      const r = await api.assistant.calendarEvents({ max_results: 5 });
      setEvents(r.events);
      setCalendarProvider(r.provider);
    } catch {
      // Service unreachable — leave the calendar empty.
    }
  }, []);

  useEffect(() => {
    refreshCalendar();
    const id = window.setInterval(refreshCalendar, 60_000);
    return () => window.clearInterval(id);
  }, [refreshCalendar]);

  async function withBusy<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function prepareMeeting() {
    const r = await withBusy(() => api.assistant.prepareMeeting());
    if (!r) return;
    setPlanModal({
      plan: r.plan,
      source: "Prepare for meeting",
      meeting: r.meeting,
      dashboardUrl: r.dashboard_url,
      openedApps: r.opened_apps,
      openedTabs: r.opened_tabs,
    });
  }

  async function morningRoutine() {
    const r = await withBusy(() => api.assistant.morningRoutine());
    if (!r) return;
    setPlanModal({ plan: r.plan, source: "Morning routine" });
  }

  async function endOfDaySummary() {
    const r = await withBusy(() => api.assistant.endOfDaySummary());
    if (!r) return;
    setSummaryModal(r);
  }

  async function runPlan(plan: Plan) {
    const r = await withBusy(() => api.assistant.runMeetingPrep(plan));
    if (!r) return;
    setPlanModal(null);
    setError(`Plan started. run_id=${r.run_id}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">AI Assistant</h1>
          <p className="text-zinc-400 mt-1 text-sm">
            Phase 5 — contextual multi-step automation (master prompt §83). Plans are
            generated but never auto-executed — you must approve each one.
          </p>
        </div>
        {/* §85 mode selector */}
        <ModeSelector mode={mode} onChange={setMode} />
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-200 rounded px-3 py-2 text-sm">
          {error}
        </div>
      )}

      {/* ---------- Quick actions ---------- */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <ActionCard
          title="Prepare for my next meeting"
          subtitle="Generate a meeting-prep plan (open agenda, tabs, notes app, presentation, dashboard)."
          onClick={prepareMeeting}
          disabled={busy}
          accent="emerald"
        />
        <ActionCard
          title="Morning routine"
          subtitle="Open mail, calendar, and today's tasks."
          onClick={morningRoutine}
          disabled={busy}
          accent="blue"
        />
        <ActionCard
          title="End of day summary"
          subtitle="Summarise today's automation activities."
          onClick={endOfDaySummary}
          disabled={busy}
          accent="amber"
        />
        <ActionCard
          title="Refresh calendar"
          subtitle={`Re-fetch the next 5 events (provider: ${calendarProvider || "—"}).`}
          onClick={refreshCalendar}
          disabled={busy}
          accent="zinc"
        />
      </section>

      {/* ---------- Research form ---------- */}
      <ResearchForm
        disabled={busy}
        onSubmit={async (topic, depth) => {
          const r = await withBusy(() => api.assistant.research(topic, depth));
          if (!r) return;
          setPlanModal({ plan: r.plan, source: `Research: ${topic}` });
        }}
      />

      {/* ---------- Organize files form ---------- */}
      <OrganizeFilesForm
        disabled={busy}
        onSubmit={async (ctx) => {
          const r = await withBusy(() => api.assistant.organizeFiles(ctx));
          if (!r) return;
          setPlanModal({ plan: r.plan, source: "Organise files" });
        }}
      />

      {/* ---------- Calendar ---------- */}
      <section className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-zinc-400">Upcoming events</div>
            <div className="mt-1 font-medium">Next 5 events</div>
          </div>
          {calendarProvider && (
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              provider: {calendarProvider}
            </div>
          )}
        </div>
        {events.length === 0 ? (
          <div className="mt-3 text-sm text-zinc-500">No upcoming events.</div>
        ) : (
          <ul className="mt-3 space-y-2">
            {events.map((e) => (
              <li
                key={e.id}
                className="bg-zinc-800 rounded px-3 py-2 text-sm flex items-center justify-between"
              >
                <div>
                  <div className="font-medium">{e.title}</div>
                  <div className="text-xs text-zinc-400 mt-0.5">
                    {new Date(e.start_at).toLocaleString()} —{" "}
                    {e.attendees?.length || 0} attendee(s)
                  </div>
                </div>
                {e.meeting_link && (
                  <a
                    href={e.meeting_link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-300 hover:underline"
                  >
                    Join
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ---------- Plan approval modal ---------- */}
      {planModal && (
        <PlanApprovalModal
          state={planModal}
          onClose={() => setPlanModal(null)}
          onApprove={() => runPlan(planModal.plan)}
          busy={busy}
        />
      )}

      {/* ---------- End-of-day summary modal ---------- */}
      {summaryModal && (
        <SummaryModal
          summary={summaryModal}
          onClose={() => setSummaryModal(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------


function ModeSelector({
  mode,
  onChange,
}: {
  mode: AssistantMode;
  onChange: (m: AssistantMode) => void;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-1 flex gap-1">
      {(["assist", "guided", "autonomous"] as AssistantMode[]).map((m) => (
        <label
          key={m}
          className={`px-3 py-1.5 text-xs uppercase tracking-wider rounded cursor-pointer transition-colors ${
            mode === m
              ? "bg-zinc-700 text-white"
              : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
          }`}
        >
          <input
            type="radio"
            name="assistant-mode"
            value={m}
            checked={mode === m}
            onChange={() => onChange(m)}
            className="sr-only"
          />
          {m}
        </label>
      ))}
    </div>
  );
}


function ActionCard({
  title,
  subtitle,
  onClick,
  disabled,
  accent,
}: {
  title: string;
  subtitle: string;
  onClick: () => void;
  disabled?: boolean;
  accent: "emerald" | "blue" | "amber" | "zinc";
}) {
  const accentClass = {
    emerald: "hover:border-emerald-500",
    blue: "hover:border-blue-500",
    amber: "hover:border-amber-500",
    zinc: "hover:border-zinc-500",
  }[accent];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`bg-zinc-800 rounded-lg p-4 text-left border border-zinc-700 transition-colors ${accentClass} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      <div className="font-medium">{title}</div>
      <div className="text-sm text-zinc-400 mt-1">{subtitle}</div>
    </button>
  );
}


function ResearchForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (topic: string, depth: number) => void;
}) {
  const [topic, setTopic] = useState("");
  const [depth, setDepth] = useState(3);
  return (
    <section className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
      <div className="text-sm text-zinc-400">Research a topic</div>
      <div className="mt-2 flex flex-col md:flex-row gap-2">
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. AI automation frameworks"
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-400">Depth</label>
          <input
            type="range"
            min={1}
            max={5}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="w-32"
          />
          <span className="text-xs text-zinc-300 w-4">{depth}</span>
        </div>
        <button
          onClick={() => topic.trim() && onSubmit(topic.trim(), depth)}
          disabled={disabled || !topic.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
        >
          Generate Plan
        </button>
      </div>
    </section>
  );
}


function OrganizeFilesForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (ctx: {
    project?: string;
    attendees?: string[];
    date_range?: { start: string; end: string };
  }) => void;
}) {
  const [project, setProject] = useState("");
  const [attendees, setAttendees] = useState("");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  return (
    <section className="bg-zinc-900 rounded-lg border border-zinc-800 p-4">
      <div className="text-sm text-zinc-400">Organise files by context</div>
      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
        <input
          type="text"
          value={project}
          onChange={(e) => setProject(e.target.value)}
          placeholder="Project name"
          className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        <input
          type="text"
          value={attendees}
          onChange={(e) => setAttendees(e.target.value)}
          placeholder="Attendees (comma-separated)"
          className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        <input
          type="date"
          value={dateStart}
          onChange={(e) => setDateStart(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
        <input
          type="date"
          value={dateEnd}
          onChange={(e) => setDateEnd(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
        />
      </div>
      <button
        onClick={() => {
          const ctx: {
            project?: string;
            attendees?: string[];
            date_range?: { start: string; end: string };
          } = {};
          if (project.trim()) ctx.project = project.trim();
          if (attendees.trim())
            ctx.attendees = attendees
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
          if (dateStart && dateEnd)
            ctx.date_range = { start: dateStart, end: dateEnd };
          onSubmit(ctx);
        }}
        disabled={disabled}
        className="mt-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
      >
        Generate Plan
      </button>
    </section>
  );
}


function PlanApprovalModal({
  state,
  onClose,
  onApprove,
  busy,
}: {
  state: PlanModalState;
  onClose: () => void;
  onApprove: () => void;
  busy: boolean;
}) {
  const { plan, source, meeting, dashboardUrl, openedApps, openedTabs } = state;
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-full max-w-2xl max-h-[80vh] overflow-auto">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              {source}
            </div>
            <div className="text-lg font-medium mt-1">{plan.goal}</div>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-200 text-sm"
          >
            Close
          </button>
        </div>

        {meeting && (
          <div className="mt-3 bg-zinc-800 rounded p-3 text-sm">
            <div className="text-xs text-zinc-400">Meeting</div>
            <div className="mt-1 font-medium">{meeting.title}</div>
            <div className="text-xs text-zinc-400 mt-0.5">
              {new Date(meeting.start_at).toLocaleString()} —{" "}
              {meeting.attendees?.length || 0} attendee(s)
            </div>
            {dashboardUrl && (
              <a
                href={dashboardUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-300 hover:underline mt-1 inline-block"
              >
                Open dashboard
              </a>
            )}
          </div>
        )}

        <div className="mt-3">
          <div className="text-xs text-zinc-400 mb-1">Proposed plan ({plan.steps.length} steps)</div>
          <ol className="text-sm space-y-1">
            {plan.steps.map((s) => (
              <li key={s.id} className="bg-zinc-800 rounded px-3 py-2">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-zinc-500">#{s.id}</span>{" "}
                    <span className="font-mono text-xs bg-zinc-700 px-1 rounded">
                      {s.action}
                    </span>
                  </div>
                  <span
                    className={`text-xs ${
                      s.risk_level === "critical"
                        ? "text-red-400"
                        : s.risk_level === "high"
                        ? "text-amber-400"
                        : s.risk_level === "medium"
                        ? "text-yellow-400"
                        : "text-emerald-400"
                    }`}
                  >
                    [{s.risk_level}]
                  </span>
                </div>
                {Object.keys(s.args || {}).length > 0 && (
                  <pre className="mt-1 text-xs text-zinc-400 overflow-x-auto">
                    {JSON.stringify(s.args, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        </div>

        {(openedApps?.length || openedTabs?.length) && (
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            {openedApps && openedApps.length > 0 && (
              <div>
                <div className="text-zinc-400 mb-1">Apps to open</div>
                <ul className="space-y-0.5">
                  {openedApps.map((a) => (
                    <li key={a} className="font-mono">
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {openedTabs && openedTabs.length > 0 && (
              <div>
                <div className="text-zinc-400 mb-1">Tabs to open</div>
                <ul className="space-y-0.5">
                  {openedTabs.map((t) => (
                    <li key={t} className="font-mono truncate">
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded text-sm"
          >
            Cancel
          </button>
          <button
            onClick={onApprove}
            disabled={busy}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
          >
            Approve & Run
          </button>
        </div>
        <div className="mt-2 text-xs text-zinc-500">
          Per master prompt §66, every step still passes through the permission engine
          before executing.
        </div>
      </div>
    </div>
  );
}


function SummaryModal({
  summary,
  onClose,
}: {
  summary: SummaryModalState;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-full max-w-2xl max-h-[80vh] overflow-auto">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              End of day summary
            </div>
            <div className="text-lg font-medium mt-1">{summary.date}</div>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-200 text-sm"
          >
            Close
          </button>
        </div>
        {summary.mock_mode && (
          <div className="mt-3 text-xs text-amber-400">
            Mock mode — no real automation runs were recorded today.
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div className="bg-zinc-800 rounded p-3">
            <div className="text-xs text-zinc-400">Total runs</div>
            <div className="text-2xl font-semibold">{summary.total_runs}</div>
          </div>
          <div className="bg-zinc-800 rounded p-3">
            <div className="text-xs text-zinc-400">Total tasks</div>
            <div className="text-2xl font-semibold">{summary.total_tasks}</div>
          </div>
        </div>
        {summary.next_meeting && (
          <div className="mt-3 bg-zinc-800 rounded p-3 text-sm">
            <div className="text-xs text-zinc-400">Next meeting</div>
            <div className="mt-1 font-medium">{summary.next_meeting.title}</div>
            <div className="text-xs text-zinc-400 mt-0.5">
              {new Date(summary.next_meeting.start_at).toLocaleString()}
            </div>
          </div>
        )}
        {summary.highlights.length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-zinc-400 mb-1">Highlights</div>
            <ul className="space-y-1 text-sm">
              {summary.highlights.map((h, i) => (
                <li key={i} className="bg-zinc-800 rounded px-3 py-2">
                  <div className="font-mono text-xs">{h.key}</div>
                  <div className="text-xs text-zinc-400 mt-0.5">
                    {typeof h.value === "string"
                      ? h.value
                      : JSON.stringify(h.value)}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

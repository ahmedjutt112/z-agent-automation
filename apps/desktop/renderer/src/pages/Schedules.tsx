/**
 * Schedules page — master prompt §24 (Scheduler), §25 (Triggers).
 *
 * Lists every scheduled job (workflow + trigger + next_run_at + enabled)
 * with pause / resume / delete buttons. Includes a "New Schedule" form
 * that lets the user pick a workflow, a trigger type, and the trigger
 * config (cron / file pattern / hotkey / webhook URL / system event).
 *
 * A reference panel explains the 8 supported trigger types.
 */

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { TriggerType } from "../lib/api";

interface ScheduleJob {
  job_id: string;
  workflow_id: string | null;
  trigger_type: string;
  next_run_time: string | null;
  is_active: boolean | null;
  source?: string | null;
}

interface TriggerTypeInfo {
  type: string;
  description: string;
  required_fields: string[];
}

interface WorkflowSummary {
  id: string;
  name: string;
  version: number;
  enabled: boolean;
}

export function Schedules() {
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [triggers, setTriggers] = useState<TriggerTypeInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  async function refresh() {
    setStatus("loading");
    setError("");
    try {
      const [jobsR, triggersR, wfs] = await Promise.all([
        api.schedules.list(),
        api.schedules.triggers(),
        api.listWorkflows(),
      ]);
      setJobs(jobsR as ScheduleJob[]);
      setTriggers(triggersR as TriggerTypeInfo[]);
      setWorkflows(wfs);
      setStatus("ready");
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAction(jobId: string, action: "pause" | "resume" | "delete") {
    setError("");
    try {
      if (action === "pause") await api.schedules.pause(jobId);
      else if (action === "resume") await api.schedules.resume(jobId);
      else await api.schedules.remove(jobId);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Schedules</h1>
          <p className="text-zinc-400 mt-1">
            Run workflows on a schedule, on file changes, on hotkeys, or via webhooks.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowForm(!showForm)}
            className="bg-zinc-700 hover:bg-zinc-600 rounded px-3 py-1.5 text-sm"
          >
            {showForm ? "Cancel" : "New Schedule"}
          </button>
          <button
            onClick={refresh}
            className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {showForm && (
        <NewScheduleForm
          workflows={workflows}
          triggers={triggers}
          onCreated={() => {
            setShowForm(false);
            refresh();
          }}
        />
      )}

      {/* Job list */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
        <div className="px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
          Scheduled Jobs ({jobs.length})
        </div>
        <div className="divide-y divide-zinc-800">
          {status === "loading" ? (
            <div className="px-4 py-8 text-center text-zinc-500 text-sm">Loading...</div>
          ) : jobs.length === 0 ? (
            <div className="px-4 py-8 text-center text-zinc-500 text-sm">
              No scheduled jobs. Click "New Schedule" to create one.
            </div>
          ) : (
            jobs.map((job) => (
              <div
                key={job.job_id}
                className="px-4 py-3 flex items-center justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">
                    {job.workflow_id ?? "(unknown workflow)"}
                  </div>
                  <div className="text-xs text-zinc-500 mt-0.5 flex gap-3 flex-wrap">
                    <span className="text-zinc-400">{job.trigger_type}</span>
                    <span>
                      next: {job.next_run_time ?? "—"}
                    </span>
                    {job.is_active !== null && (
                      <span className={job.is_active ? "text-emerald-400" : "text-amber-400"}>
                        {job.is_active ? "active" : "paused"}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-zinc-600 mt-0.5 font-mono truncate">
                    {job.job_id}
                  </div>
                </div>
                <div className="flex gap-2">
                  {job.is_active && (
                    <button
                      onClick={() => handleAction(job.job_id, "pause")}
                      className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs"
                    >
                      Pause
                    </button>
                  )}
                  {!job.is_active && (
                    <button
                      onClick={() => handleAction(job.job_id, "resume")}
                      className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-xs"
                    >
                      Resume
                    </button>
                  )}
                  <button
                    onClick={() => handleAction(job.job_id, "delete")}
                    className="bg-red-900/40 hover:bg-red-800 text-red-200 rounded px-3 py-1.5 text-xs"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Trigger reference panel */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
        <div className="px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
          Trigger Types ({triggers.length})
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-4">
          {triggers.map((t) => (
            <div key={t.type} className="bg-zinc-950 border border-zinc-800 rounded p-3">
              <div className="text-sm font-medium">{t.type}</div>
              <div className="text-xs text-zinc-400 mt-1">{t.description}</div>
              <div className="text-xs text-zinc-500 mt-2">
                Required fields:{" "}
                <span className="font-mono">{t.required_fields.join(", ") || "(none)"}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function NewScheduleForm({
  workflows,
  triggers,
  onCreated,
}: {
  workflows: WorkflowSummary[];
  triggers: TriggerTypeInfo[];
  onCreated: () => void;
}) {
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id ?? "");
  const [triggerType, setTriggerType] = useState<TriggerType>("schedule");
  const [cron, setCron] = useState("0 * * * *");
  const [filePattern, setFilePattern] = useState("*.txt");
  const [hotkey, setHotkey] = useState("ctrl+shift+a");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [systemEvent, setSystemEvent] = useState("startup");
  const [timezone, setTimezone] = useState("UTC");
  const [misfireGrace, setMisfireGrace] = useState(60);
  const [maxConcurrent, setMaxConcurrent] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const triggerConfig: Record<string, unknown> = { type: triggerType };
      if (triggerType === "schedule") {
        triggerConfig.schedule_type = "cron";
        triggerConfig.cron = cron;
        triggerConfig.timezone = timezone;
        triggerConfig.misfire_grace_time = misfireGrace;
        triggerConfig.max_concurrent = maxConcurrent;
      } else if (triggerType === "file") {
        triggerConfig.file_pattern = filePattern;
      } else if (triggerType === "hotkey") {
        triggerConfig.hotkey = hotkey;
      } else if (triggerType === "webhook") {
        triggerConfig.webhook_url = webhookUrl;
      } else if (triggerType === "system") {
        triggerConfig.event = systemEvent;
      }
      await api.schedules.create({ workflow_id: workflowId, trigger_config: triggerConfig });
      onCreated();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4"
    >
      <h2 className="text-sm uppercase tracking-wider text-zinc-500">New Schedule</h2>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-zinc-500">Workflow</label>
          <select
            value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            required
          >
            {workflows.length === 0 ? (
              <option value="">(no workflows)</option>
            ) : (
              workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} (v{w.version})
                </option>
              ))
            )}
          </select>
        </div>

        <div>
          <label className="text-xs text-zinc-500">Trigger Type</label>
          <select
            value={triggerType}
            onChange={(e) => setTriggerType(e.target.value as TriggerType)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="schedule">Schedule (cron)</option>
            <option value="file">File (file_pattern)</option>
            <option value="application">Application (launch/close)</option>
            <option value="browser">Browser (url_pattern)</option>
            <option value="hotkey">Hotkey (global shortcut)</option>
            <option value="webhook">Webhook (POST endpoint)</option>
            <option value="system">System (startup/idle)</option>
            <option value="manual">Manual (no auto trigger)</option>
          </select>
        </div>
      </div>

      {/* Dynamic trigger config */}
      {triggerType === "schedule" && (
        <>
          <div>
            <label className="text-xs text-zinc-500">Cron expression</label>
            <input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm font-mono"
              placeholder="0 * * * *"
              required
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-zinc-500">Timezone</label>
              <input
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">Misfire grace (s)</label>
              <input
                type="number"
                value={misfireGrace}
                onChange={(e) => setMisfireGrace(Number(e.target.value))}
                className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
                min={1}
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">Max concurrent</label>
              <input
                type="number"
                value={maxConcurrent}
                onChange={(e) => setMaxConcurrent(Number(e.target.value))}
                className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
                min={1}
              />
            </div>
          </div>
        </>
      )}

      {triggerType === "file" && (
        <div>
          <label className="text-xs text-zinc-500">File pattern (glob)</label>
          <input
            value={filePattern}
            onChange={(e) => setFilePattern(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            placeholder="*.txt"
            required
          />
        </div>
      )}

      {triggerType === "hotkey" && (
        <div>
          <label className="text-xs text-zinc-500">Hotkey</label>
          <input
            value={hotkey}
            onChange={(e) => setHotkey(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            placeholder="ctrl+shift+a"
            required
          />
        </div>
      )}

      {triggerType === "webhook" && (
        <div>
          <label className="text-xs text-zinc-500">Webhook URL (optional)</label>
          <input
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            placeholder="/webhooks/abc-123"
          />
          <p className="text-xs text-zinc-500 mt-1">
            A unique URL will be generated if left blank.
          </p>
        </div>
      )}

      {triggerType === "system" && (
        <div>
          <label className="text-xs text-zinc-500">System event</label>
          <select
            value={systemEvent}
            onChange={(e) => setSystemEvent(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="startup">Startup</option>
            <option value="login">Login</option>
            <option value="idle">Idle</option>
            <option value="network_available">Network available</option>
          </select>
        </div>
      )}

      {error && <div className="text-xs text-red-400">{error}</div>}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={busy || !workflowId}
          className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Creating..." : "Create Schedule"}
        </button>
      </div>
    </form>
  );
}

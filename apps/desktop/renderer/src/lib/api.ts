/**
 * Automation API client — typed wrappers around fetch() to the Python service.
 * Master prompt §75 — typed API contract.
 */

const BASE_URL = "http://127.0.0.1:8765";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export type TriggerType =
  | "schedule"
  | "file"
  | "application"
  | "browser"
  | "hotkey"
  | "webhook"
  | "system"
  | "manual";

export interface ToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  permission_level: string;
  risk_level: RiskLevel;
  timeout_ms: number;
  rollback_strategy?: string | null;
  verification_strategy?: string | null;
}

export interface PlanStep {
  id: string;
  action: string;
  args: Record<string, unknown>;
  risk_level: RiskLevel;
  confidence: number;
  timeout_ms: number;
  retry_count: number;
  fallback?: string | null;
  verification?: string | null;
}

export interface Plan {
  id: string;
  goal: string;
  steps: PlanStep[];
  required_permissions: string[];
  overall_risk: RiskLevel;
  potential_side_effects: string[];
  estimated_duration_seconds: number;
  variables: Record<string, string>;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  version: number;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Workflow schema (master prompt §21) — mirrors the pydantic models in
// automation_service/models.py.
// ---------------------------------------------------------------------------

export interface WorkflowTrigger {
  type: TriggerType;
  cron?: string | null;
  file_pattern?: string | null;
  hotkey?: string | null;
  webhook_url?: string | null;
  timezone: string;
}

export type OnErrorAction = "stop" | "continue" | "jump_to" | "retry";

export interface WorkflowNode {
  id: string;
  /** The tool / action name, e.g. "browser.click" or "if". */
  type: string;
  /** Tool input arguments. May also carry visual metadata under "_"-prefixed keys. */
  args: Record<string, unknown>;
  /** Next node id (linear chain). */
  next: string | null;
  /** Node id to jump to on error. */
  on_error: string | null;
  timeout_ms: number;
  retry_count: number;
  retry_delay_ms: number;
  /** Visual-only fields used by the React Flow canvas. Optional because
   * older workflows persisted before this editor existed don't have them. */
  position?: { x: number; y: number };
  visual_type?:
    | "start"
    | "end"
    | "action"
    | "condition"
    | "loop"
    | "notification"
    | "ai_decision";
  label?: string;
  risk_level?: RiskLevel;
  on_error_action?: OnErrorAction;
}

export interface Workflow {
  id: string;
  name: string;
  version: number;
  description?: string | null;
  trigger: WorkflowTrigger;
  nodes: WorkflowNode[];
  variables: Record<string, string>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description?: string | null;
  trigger: WorkflowTrigger;
  node_count: number;
  template: Workflow;
}

export interface WorkflowVersion {
  version: number;
  filename: string;
  saved_at: string;
  size_bytes: number;
}

// ---------------------------------------------------------------------------
// Marketplace types — master prompt §52
// ---------------------------------------------------------------------------

export interface MarketplaceCategory {
  category: string;
  label: string;
  count: number;
}

export interface MarketplaceTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  author: string;
  version: string;
  downloads_count: number;
  rating: number;
  rating_count: number;
  workflow: Workflow;
  tags: string[];
  created_at: string;
  updated_at: string;
  permissions_required: string[];
  risk_level: RiskLevel;
  featured: boolean;
}

export interface InstallResponse {
  workflow: Workflow;
  permissions_required: string[];
  risk_level: RiskLevel;
  warnings: string[];
  template_id: string;
  installed: boolean;
}

export interface WorkflowValidation {
  valid: boolean;
  errors: string[];
  permissions_required: string[];
  risk_level: RiskLevel;
}

export interface WorkflowImportResponse extends WorkflowValidation {
  workflow: Workflow;
  warnings: string[];
  imported: boolean;
}

export interface WorkflowPermissions {
  workflow_id: string;
  permissions_required: string[];
  risk_level: RiskLevel;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Logs + Screenshots + OCR types (master prompt §15, §38, §57, §73)
// ---------------------------------------------------------------------------

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  tool?: string | null;
  task_id?: string | null;
}

export interface ScreenshotMetadata {
  id: string;
  task_id?: string | null;
  profile_id?: string | null;
  file_path: string;
  width?: number | null;
  height?: number | null;
  metadata_json?: Record<string, unknown> | null;
  created_at: string;
}

export interface OCRBoundingBox {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
}

export interface OCRResult {
  text: string;
  bounding_boxes: OCRBoundingBox[];
}

// ---------------------------------------------------------------------------
// Calendar types — master prompt §83 (Phase 5 AI OS Assistant)
// ---------------------------------------------------------------------------

export interface CalendarAttendee {
  name?: string | null;
  email?: string | null;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  location?: string | null;
  attendees: CalendarAttendee[];
  description?: string | null;
  conference_url?: string | null;
  meeting_link?: string | null;
  metadata?: Record<string, unknown>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(`${resp.status}: ${body.detail || "request failed"}`);
  }
  return await resp.json() as T;
}

export const api = {
  health: () => request<{ status: string; mock_mode: boolean; kill_switch: boolean }>("/health"),

  listTools: () => request<ToolSpec[]>("/tools"),

  createPlan: (goal: string) =>
    request<Plan>(`/task/plan?goal=${encodeURIComponent(goal)}`, { method: "POST" }),

  runPlan: (plan: Plan, mode = "guided") =>
    request<{ run_id: string; plan_id: string; status: string }>("/task/run", {
      method: "POST",
      body: JSON.stringify({ ...plan, mode }),
    }),

  cancelRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/task/cancel/${runId}`, { method: "POST" }),

  // ---- Workflow CRUD (master prompt §21, §34) ----

  listWorkflows: () => request<WorkflowSummary[]>("/workflow"),

  /** POST /workflow — save a new workflow (or overwrite by id). */
  saveWorkflow: (workflow: Workflow) =>
    request<{ id: string; saved: boolean }>("/workflow", {
      method: "POST",
      body: JSON.stringify(workflow),
    }),

  /** GET /workflow/{id} — full workflow object. */
  getWorkflow: (id: string) =>
    request<Workflow>(`/workflow/${encodeURIComponent(id)}`),

  /** PUT /workflow/{id} — partial update (server bumps version on node changes). */
  updateWorkflow: (id: string, workflow: Partial<Workflow>) =>
    request<{ id: string; updated: boolean; version: number; updated_at: string }>(
      `/workflow/${encodeURIComponent(id)}`,
      { method: "PUT", body: JSON.stringify(workflow) },
    ),

  /** DELETE /workflow/{id} */
  deleteWorkflow: (id: string) =>
    request<{ id: string; deleted: boolean }>(
      `/workflow/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),

  /** POST /workflow/{id}/duplicate */
  duplicateWorkflow: (id: string) =>
    request<{ id: string; source_id: string; duplicated: boolean }>(
      `/workflow/${encodeURIComponent(id)}/duplicate`,
      { method: "POST" },
    ),

  /** GET /workflow/{id}/versions */
  listWorkflowVersions: (id: string) =>
    request<WorkflowVersion[]>(`/workflow/${encodeURIComponent(id)}/versions`),

  /** POST /workflow/{id}/run — executes a saved workflow via WorkflowExecutor. */
  runWorkflow: (id: string) =>
    request<{ run_id: string; workflow_id: string; status: string; mock_mode: boolean }>(
      `/workflow/${encodeURIComponent(id)}/run`,
      { method: "POST" },
    ),

  /** GET /workflow/templates — built-in starter workflows. */
  listWorkflowTemplates: () =>
    request<WorkflowTemplate[]>("/workflow/templates"),

  // ---- Workflow import / export / validate / permissions (§51) ----

  /**
   * POST /workflow/import — validates + imports a workflow JSON.
   * The imported workflow is saved with enabled=false (master prompt §51:
   * "Never execute imported workflows automatically"). The response
   * includes the permissions_required + risk_level so the UI can show a
   * permission-review modal before the user enables it.
   */
  importWorkflow: (workflowJson: string, profileId?: string) =>
    request<WorkflowImportResponse>("/workflow/import", {
      method: "POST",
      body: JSON.stringify({
        workflow_json: workflowJson,
        profile_id: profileId ?? null,
      }),
    }),

  /**
   * GET /workflow/{id}/export — returns the workflow JSON as a file
   * attachment (Content-Type: application/json, Content-Disposition:
   * attachment; filename=...).
   */
  exportWorkflow: (id: string): Promise<Blob> =>
    fetch(`${BASE_URL}/workflow/${encodeURIComponent(id)}/export`).then((r) => {
      if (!r.ok) {
        return r
          .json()
          .catch(() => ({ detail: r.statusText }))
          .then((body) => {
            throw new Error(`${r.status}: ${body.detail || "export failed"}`);
          });
      }
      return r.blob();
    }),

  /**
   * POST /workflow/validate — validates a workflow JSON without saving.
   * Returns {valid, errors, permissions_required, risk_level}.
   */
  validateWorkflow: (workflowJson: string) =>
    request<WorkflowValidation>("/workflow/validate", {
      method: "POST",
      body: JSON.stringify({ workflow_json: workflowJson }),
    }),

  /**
   * GET /workflow/{id}/permissions — returns the permissions required by
   * this workflow (master prompt §51: "Show permission requirements before
   * execution").
   */
  workflowPermissions: (id: string) =>
    request<WorkflowPermissions>(`/workflow/${encodeURIComponent(id)}/permissions`),

  // ---- Logs (master prompt §38, §57, §73) ----
  // The /logs/stream WebSocket is opened directly by the renderer (see
  // DevPanel.tsx); these helpers cover the HTTP surface.
  logs: {
    /** GET /logs/recent — last N entries, optionally filtered. */
    recent: (
      limit = 100,
      level?: string,
      tool?: string,
      taskId?: string,
    ): Promise<LogEntry[]> => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (level) params.set("level", level);
      if (tool) params.set("tool", tool);
      if (taskId) params.set("task_id", taskId);
      return request<LogEntry[]>(`/logs/recent?${params.toString()}`);
    },

    /** GET /logs/export?format=...&since=... — returns a Blob (json|csv|txt). */
    exportLogs: (
      format: "json" | "csv" | "txt",
      since?: string,
      level?: string,
      tool?: string,
      taskId?: string,
    ): Promise<Blob> => {
      const params = new URLSearchParams({ format });
      if (since) params.set("since", since);
      if (level) params.set("level", level);
      if (tool) params.set("tool", tool);
      if (taskId) params.set("task_id", taskId);
      return fetch(`${BASE_URL}/logs/export?${params.toString()}`).then((r) => {
        if (!r.ok) {
          return r
            .json()
            .catch(() => ({ detail: r.statusText }))
            .then((body) => {
              throw new Error(`${r.status}: ${body.detail || "export failed"}`);
            });
        }
        return r.blob();
      });
    },
  },

  // ---- Screenshots (master prompt §15, §73) ----
  screenshots: {
    /** GET /screenshots — list recent screenshots (DB or filesystem). */
    list: (
      limit = 50,
      taskId?: string,
      profileId?: string,
    ): Promise<ScreenshotMetadata[]> => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (taskId) params.set("task_id", taskId);
      if (profileId) params.set("profile_id", profileId);
      return request<ScreenshotMetadata[]>(`/screenshots?${params.toString()}`);
    },

    /** GET /screenshots/{id} — raw PNG bytes. */
    get: (id: string): Promise<Blob> =>
      fetch(`${BASE_URL}/screenshots/${encodeURIComponent(id)}`).then((r) => {
        if (!r.ok) {
          return r
            .json()
            .catch(() => ({ detail: r.statusText }))
            .then((body) => {
              throw new Error(`${r.status}: ${body.detail || "fetch failed"}`);
            });
        }
        return r.blob();
      }),

    /** GET /screenshots/{id}/metadata — just the metadata dict. */
    metadata: (id: string): Promise<ScreenshotMetadata> =>
      request<ScreenshotMetadata>(`/screenshots/${encodeURIComponent(id)}/metadata`),

    /** DELETE /screenshots/{id} — removes the file + DB row. */
    delete: (id: string): Promise<{ deleted: boolean }> =>
      request<{ deleted: boolean }>(`/screenshots/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),

    /** POST /screenshots/{id}/ocr — runs OCR, returns text + bounding boxes. */
    ocr: (id: string): Promise<OCRResult> =>
      request<OCRResult>(`/screenshots/${encodeURIComponent(id)}/ocr`, {
        method: "POST",
      }),
  },

  emergencyStop: () =>
    request<{ engaged: boolean }>("/emergency-stop", { method: "POST" }),
  emergencyReset: () =>
    request<{ engaged: boolean }>("/emergency-reset", { method: "POST" }),

  // ---- Marketplace (master prompt §52 — template marketplace) ----
  // Imported workflows MUST be sandboxed + permission-scanned (§51).
  // The install endpoint returns the workflow with enabled=false so the
  // user must manually enable it before any node can run.
  marketplace: {
    /** GET /marketplace/templates — list templates, optionally filtered. */
    listTemplates: (params?: {
      category?: string;
      tag?: string;
      limit?: number;
    }): Promise<MarketplaceTemplate[]> => {
      const qs = new URLSearchParams();
      if (params?.category) qs.set("category", params.category);
      if (params?.tag) qs.set("tag", params.tag);
      if (params?.limit) qs.set("limit", String(params.limit));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<MarketplaceTemplate[]>(`/marketplace/templates${suffix}`);
    },

    /** GET /marketplace/templates/{id} — full template (incl. workflow). */
    getTemplate: (id: string) =>
      request<MarketplaceTemplate>(`/marketplace/templates/${encodeURIComponent(id)}`),

    /** GET /marketplace/search?q=... — free-text search. */
    searchTemplates: (q: string) =>
      request<MarketplaceTemplate[]>(
        `/marketplace/search?q=${encodeURIComponent(q)}`,
      ),

    /**
     * POST /marketplace/install/{id} — installs the template as a user
     * workflow. The workflow is saved with enabled=false; the response
     * includes permissions_required + risk_level + warnings so the UI
     * can render a permission-review modal before the user enables it.
     */
    installTemplate: (id: string, profileId?: string) =>
      request<InstallResponse>(`/marketplace/install/${encodeURIComponent(id)}`, {
        method: "POST",
        body: JSON.stringify({ profile_id: profileId ?? null }),
      }),

    /** DELETE /marketplace/install/{id} — uninstalls the workflow. */
    uninstallTemplate: (id: string, profileId?: string) =>
      request<{ uninstalled: boolean; template_id: string }>(
        `/marketplace/install/${encodeURIComponent(id)}`,
        {
          method: "DELETE",
          body: JSON.stringify({ profile_id: profileId ?? null }),
        },
      ),

    /** POST /marketplace/rate/{id} — add a 1-5 star rating. */
    rateTemplate: (id: string, rating: number) =>
      request<{ template_id: string; rating: number; rating_count: number }>(
        `/marketplace/rate/${encodeURIComponent(id)}`,
        { method: "POST", body: JSON.stringify({ rating }) },
      ),

    /** POST /marketplace/submit — publish a user-submitted template. */
    submitTemplate: (body: {
      workflow: Workflow;
      author: string;
      category: string;
      tags: string[];
    }) =>
      request<{ template_id: string; submitted: boolean }>(
        "/marketplace/submit",
        { method: "POST", body: JSON.stringify(body) },
      ),

    /** GET /marketplace/categories — list every category with counts. */
    listCategories: () =>
      request<{ categories: MarketplaceCategory[] }>("/marketplace/categories"),

    /** GET /marketplace/featured — 6 featured templates. */
    getFeatured: () =>
      request<MarketplaceTemplate[]>("/marketplace/featured"),
  },

  // ---- OAuth (master prompt §54) ----
  oauth: {
    start: (provider: string) =>
      request<{ authorization_url: string; state: string }>(
        `/oauth/${encodeURIComponent(provider)}/start`,
      ),
    status: () =>
      request<{
        providers: Array<{
          provider: string;
          configured: boolean;
          connected: boolean;
        }>;
      }>("/oauth/status"),
    disconnect: (provider: string) =>
      request<{ provider: string; disconnected: boolean }>(
        `/oauth/${encodeURIComponent(provider)}/disconnect`,
        { method: "POST" },
      ),
  },

  // ---- Messaging integrations (master prompt §54) ----
  integrations: {
    list: () =>
      request<{
        integrations: Array<{
          name: string;
          category: string;
          configured: boolean;
          status: string;
        }>;
      }>("/integrations"),

    sendEmail: (to: string, subject: string, body: string, html = false) =>
      request<{ sent: boolean; to: string[]; subject: string; mock?: boolean }>(
        "/integrations/email/send",
        { method: "POST", body: JSON.stringify({ to, subject, body, html }) },
      ),

    emailInbox: (limit = 10) =>
      request<{
        messages: Array<{
          id: string;
          from: string;
          to: string[];
          subject: string;
          body: string;
          received_at: string | null;
          read: boolean;
        }>;
      }>(`/integrations/email/inbox?limit=${limit}`),

    sendWhatsApp: (to: string, message: string) =>
      request<{ message_id: string; mock?: boolean }>(
        "/integrations/whatsapp/send-text",
        { method: "POST", body: JSON.stringify({ to, message }) },
      ),

    sendTelegram: (chat_id: string | number, text: string, parse_mode = "HTML") =>
      request<{ message_id: number | string; mock?: boolean }>(
        "/integrations/telegram/send",
        { method: "POST", body: JSON.stringify({ chat_id, text, parse_mode }) },
      ),

    sendDiscord: (channel_id: string | number, content: string) =>
      request<{ message_id: string; mock?: boolean }>(
        "/integrations/discord/send",
        { method: "POST", body: JSON.stringify({ channel_id, content }) },
      ),
  },

  // ---- Voice control (master prompt section 46) ----
  // Pipeline: Microphone -> STT -> AI Planner -> Permission Engine -> Automation
  // CRITICAL: voice commands NEVER bypass security confirmation.
  // listenAndPlan returns the plan WITHOUT executing it; the frontend
  // must display it and require the user to click "Approve & Run"
  // before calling listenAndExecute.
  voice: {
    /** POST /voice/listen — capture + transcribe a single utterance. */
    listen: () =>
      request<{ transcript: string }>("/voice/listen", { method: "POST" }),

    /** POST /voice/speak — synthesize + play TTS audio. */
    speak: (text: string, voice = "default") =>
      request<{ spoken: boolean }>("/voice/speak", {
        method: "POST",
        body: JSON.stringify({ text, voice }),
      }),

    /**
     * POST /voice/listen-and-plan — full pipeline up to plan generation.
     * Returns {transcript, plan} WITHOUT executing the plan.
     * The frontend MUST display the plan and require explicit user
     * approval before calling listenAndExecute.
     */
    listenAndPlan: () =>
      request<{ transcript: string; plan: Plan }>(
        "/voice/listen-and-plan",
        { method: "POST" },
      ),

    /**
     * POST /voice/listen-and-execute — execute an already-approved plan
     * via WorkflowExecutor. The permission engine is re-evaluated
     * (defense in depth) before execution begins.
     */
    listenAndExecute: (plan: Plan) =>
      request<{ run_id: string; plan_id: string; status: string }>(
        "/voice/listen-and-execute",
        { method: "POST", body: JSON.stringify({ plan }) },
      ),

    /** POST /voice/start-continuous — start background wake-word listening. */
    startContinuous: () =>
      request<{ started: boolean; wake_word: string; mock_mode: boolean }>(
        "/voice/start-continuous",
        { method: "POST" },
      ),

    /** POST /voice/stop-continuous — stop background listening. */
    stopContinuous: () =>
      request<{ stopped: boolean; wake_word: string }>(
        "/voice/stop-continuous",
        { method: "POST" },
      ),

    /** GET /voice/status — current voice subsystem status. */
    status: () =>
      request<{
        listening: boolean;
        wake_word: string;
        last_transcript: string | null;
        mock_mode: boolean;
      }>("/voice/status"),
  },

  // ---- AI Assistant (master prompt §83 — Phase 5) ----
  // High-level contextual automation: prepare-meeting, morning routine,
  // end-of-day summary, research, file organisation, calendar lookup.
  // CRITICAL: every plan-returning endpoint returns executed=false; the
  // frontend MUST display the plan and require explicit user approval
  // before calling runMeetingPrep (or /task/run).
  assistant: {
    /** POST /assistant/prepare-meeting — generate a meeting-prep Plan. */
    prepareMeeting: (meetingId?: string) =>
      request<{
        plan: Plan;
        meeting: CalendarEvent | null;
        opened_apps: string[];
        opened_tabs: string[];
        organized_files: string[];
        dashboard_url: string | null;
        executed: boolean;
      }>("/assistant/prepare-meeting", {
        method: "POST",
        body: JSON.stringify({ meeting_id: meetingId ?? null }),
      }),

    /** POST /assistant/run-meeting-prep — execute an approved plan. */
    runMeetingPrep: (plan: Plan) =>
      request<{ run_id: string; plan_id: string; status: string; executed: boolean }>(
        "/assistant/run-meeting-prep",
        { method: "POST", body: JSON.stringify({ plan }) },
      ),

    /** POST /assistant/organize-files — generate a file-organisation Plan. */
    organizeFiles: (context: {
      project?: string;
      attendees?: string[];
      date_range?: { start: string; end: string };
      destination?: string;
    }) =>
      request<{ plan: Plan; executed: boolean }>("/assistant/organize-files", {
        method: "POST",
        body: JSON.stringify({ context }),
      }),

    /** POST /assistant/morning-routine — generate a morning-routine Plan. */
    morningRoutine: () =>
      request<{ plan: Plan; executed: boolean }>("/assistant/morning-routine", {
        method: "POST",
      }),

    /** GET /assistant/end-of-day-summary — summary of today's activities. */
    endOfDaySummary: () =>
      request<{
        date: string;
        total_runs: number;
        total_tasks: number;
        highlights: Array<{ key: string; value: unknown; at: string }>;
        task_context: Array<{ key: string; value: unknown; at: string }>;
        next_meeting?: { title: string; start_at: string; meeting_link?: string | null } | null;
        mock_mode?: boolean;
      }>("/assistant/end-of-day-summary"),

    /** POST /assistant/research — generate a research Plan. */
    research: (topic: string, depth = 3) =>
      request<{ plan: Plan; executed: boolean }>("/assistant/research", {
        method: "POST",
        body: JSON.stringify({ topic, depth }),
      }),

    /** GET /assistant/calendar/next-meeting — the next upcoming event. */
    nextMeeting: () =>
      request<{ next_meeting: CalendarEvent | null }>(
        "/assistant/calendar/next-meeting",
      ),

    /** GET /assistant/calendar/events — list events in a window. */
    calendarEvents: (params?: {
      time_min?: string;
      time_max?: string;
      max_results?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.time_min) qs.set("time_min", params.time_min);
      if (params?.time_max) qs.set("time_max", params.time_max);
      if (params?.max_results) qs.set("max_results", String(params.max_results));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{
        events: CalendarEvent[];
        count: number;
        provider: string;
      }>(`/assistant/calendar/events${suffix}`);
    },
  },

  // ---- Task Recorder (master prompt §22, §35) ----
  // Captures raw mouse / keyboard / browser / file events and compiles them
  // into a Workflow. The backend TaskRecorder is in mock_mode by default —
  // start() just flips a flag and stop() returns a fake Recording with 3-4
  // sample events so the to-workflow pipeline can be exercised.
  recorder: {
    start: () => request<{ recording: boolean; paused: boolean; events_count: number; started_at: string | null; mock_mode: boolean }>("/recorder/start", { method: "POST" }),
    pause: () => request<{ recording: boolean; paused: boolean; events_count: number; mock_mode: boolean }>("/recorder/pause", { method: "POST" }),
    resume: () => request<{ recording: boolean; paused: boolean; events_count: number; mock_mode: boolean }>("/recorder/resume", { method: "POST" }),
    stop: () => request<{ recording: unknown; status: string; mock_mode: boolean }>("/recorder/stop", { method: "POST" }),
    status: () => request<{ recording: boolean; paused: boolean; events_count: number; started_at: string | null; mock_mode: boolean }>("/recorder/status"),
    events: () => request<{ events: unknown[]; count: number }>("/recorder/events"),
    toWorkflow: (name?: string) =>
      request<{ workflow: Workflow; events_count: number; mock_mode: boolean }>(
        "/recorder/to-workflow",
        { method: "POST", body: JSON.stringify({ name: name ?? null }) },
      ),
    deleteEvent: (index: number) =>
      request<{ removed: unknown; remaining: number }>(
        `/recorder/events/${index}`,
        { method: "DELETE" },
      ),
  },

  // ---- Browser sessions (master prompt §16, §17) ----
  // In mock mode the underlying Playwright instance is never started —
  // the routes still record session metadata so the UI's session list works.
  browser: {
    listSessions: () =>
      request<{ sessions: unknown[]; count: number; mock_mode: boolean }>("/browser/sessions"),
    createSession: (body: { browser?: string; headless?: boolean; session_id?: string }) =>
      request<{ session: unknown; mock_mode: boolean }>("/browser/session", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    closeSession: (sessionId: string) =>
      request<{ session_id: string; closed: boolean; mock_mode: boolean }>(
        `/browser/session/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" },
      ),
    navigate: (sessionId: string, url: string) =>
      request<{ session_id: string; url: string; title: string | null; mock_mode: boolean; result: unknown }>(
        `/browser/session/${encodeURIComponent(sessionId)}/navigate`,
        { method: "POST", body: JSON.stringify({ url }) },
      ),
    click: (sessionId: string, selector: string) =>
      request<{ session_id: string; selector: string; mock_mode: boolean; result: unknown }>(
        `/browser/session/${encodeURIComponent(sessionId)}/click`,
        { method: "POST", body: JSON.stringify({ selector }) },
      ),
    type: (sessionId: string, selector: string, text: string) =>
      request<{ session_id: string; selector: string; length: number; mock_mode: boolean; result: unknown }>(
        `/browser/session/${encodeURIComponent(sessionId)}/type`,
        { method: "POST", body: JSON.stringify({ selector, text }) },
      ),
    extract: (sessionId: string, selector: string) =>
      request<{ session_id: string; selector: string; text: string; mock_mode: boolean; result: unknown }>(
        `/browser/session/${encodeURIComponent(sessionId)}/extract`,
        { method: "POST", body: JSON.stringify({ selector }) },
      ),
    screenshot: (sessionId: string) =>
      request<{ session_id: string; mock_mode: boolean; result: unknown }>(
        `/browser/session/${encodeURIComponent(sessionId)}/screenshot`,
        { method: "POST" },
      ),
  },

  // ---- Files (master prompt §18, §55 File Security) ----
  // Every path goes through the backend _validate_path allowlist. Blocked
  // paths (/etc, /usr, C:/Windows etc.) return 403. file.delete is CRITICAL
  // risk — pass approved=true after the user confirms.
  files: {
    list: (path: string, pattern = "*") =>
      request<{ path: string; count: number; entries: unknown[]; mock_mode: boolean }>(
        `/files/list?path=${encodeURIComponent(path)}&pattern=${encodeURIComponent(pattern)}`,
      ),
    read: (path: string, encoding = "utf-8", maxBytes = 1_048_576) =>
      request<{ path: string; size: number; text: string; encoding: string; mock_mode: boolean }>(
        `/files/read?path=${encodeURIComponent(path)}&encoding=${encodeURIComponent(encoding)}&max_bytes=${maxBytes}`,
      ),
    write: (path: string, content: string, encoding = "utf-8") =>
      request<{ path: string; size: number; mock_mode: boolean }>("/files/write", {
        method: "POST",
        body: JSON.stringify({ path, content, encoding }),
      }),
    move: (source: string, destination: string) =>
      request<{ source: string; destination: string; mock_mode: boolean }>("/files/move", {
        method: "POST",
        body: JSON.stringify({ source, destination }),
      }),
    rename: (path: string, newName: string) =>
      request<{ old: string; new: string; mock_mode: boolean }>("/files/rename", {
        method: "POST",
        body: JSON.stringify({ path, new_name: newName }),
      }),
    copy: (source: string, destination: string) =>
      request<{ source: string; destination: string; size: number; mock_mode: boolean }>("/files/copy", {
        method: "POST",
        body: JSON.stringify({ source, destination }),
      }),
    delete: (path: string, approved: boolean) =>
      request<{ path: string; deleted: boolean; mock_mode: boolean }>("/files/delete", {
        method: "POST",
        body: JSON.stringify({ path, approved }),
      }),
    download: (path: string): Promise<Blob> =>
      fetch(`${BASE_URL}/files/download?path=${encodeURIComponent(path)}`).then((r) => {
        if (!r.ok) {
          return r
            .json()
            .catch(() => ({ detail: r.statusText }))
            .then((body) => {
              throw new Error(`${r.status}: ${body.detail || "download failed"}`);
            });
        }
        return r.blob();
      }),
  },

  // ---- History (master prompt §36) ----
  // Task history pulled from the SQLAlchemy tasks / task_steps / task_logs /
  // screenshots / automation_history tables. Returns empty lists when the
  // DB is unavailable (mock mode) so the UI renders an empty state.
  history: {
    listTasks: (params?: {
      limit?: number;
      offset?: number;
      status?: string;
      date_from?: string;
      date_to?: string;
      search?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      if (params?.offset !== undefined) qs.set("offset", String(params.offset));
      if (params?.status) qs.set("status", params.status);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.search) qs.set("search", params.search);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{
        tasks: Array<{
          id: string;
          name: string;
          status: string;
          profile_id?: string | null;
          started_at?: string | null;
          finished_at?: string | null;
          created_at?: string | null;
        }>;
        count: number;
        limit: number;
        offset: number;
        mock_mode: boolean;
      }>(`/history/tasks${suffix}`);
    },
    getTask: (taskId: string) =>
      request<{ task: unknown; steps: unknown[]; logs: unknown[]; mock_mode: boolean }>(
        `/history/tasks/${encodeURIComponent(taskId)}`,
      ),
    getTaskScreenshots: (taskId: string) =>
      request<{ screenshots: unknown[]; count: number; mock_mode: boolean }>(
        `/history/tasks/${encodeURIComponent(taskId)}/screenshots`,
      ),
    getTaskLogs: (taskId: string) =>
      request<{ logs: unknown[]; count: number; mock_mode: boolean }>(
        `/history/tasks/${encodeURIComponent(taskId)}/logs`,
      ),
    rerunTask: (taskId: string) =>
      request<{ task_id: string; new_run_id: string | null; started: boolean; mock_mode: boolean }>(
        `/history/tasks/${encodeURIComponent(taskId)}/rerun`,
        { method: "POST" },
      ),
    export: (params?: {
      status?: string;
      date_from?: string;
      date_to?: string;
      search?: string;
    }): Promise<Blob> => {
      const qs = new URLSearchParams();
      if (params?.status) qs.set("status", params.status);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.search) qs.set("search", params.search);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return fetch(`${BASE_URL}/history/export${suffix}`).then((r) => {
        if (!r.ok) {
          return r
            .json()
            .catch(() => ({ detail: r.statusText }))
            .then((body) => {
              throw new Error(`${r.status}: ${body.detail || "export failed"}`);
            });
        }
        return r.blob();
      });
    },
  },

  // ---- AI Models + Providers + Credentials (master prompt §6, §28, §57) ----
  // 52 AI providers. Credentials are stored in the OS keyring (never
  // returned in API responses — only the has_credential flag is exposed).
  aiModels: {
    list: (provider?: string) => {
      const qs = new URLSearchParams();
      if (provider) qs.set("provider", provider);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{ models: unknown[]; count: number; provider: string | null; mock_mode: boolean }>(
        `/ai-models${suffix}`,
      );
    },
    sync: (provider?: string) => {
      const qs = new URLSearchParams();
      if (provider) qs.set("provider", provider);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{ synced: Record<string, number>; mock_mode: boolean }>(
        `/ai-models/sync${suffix}`,
        { method: "POST" },
      );
    },
    listProviders: () =>
      request<{
        providers: Array<{
          name: string;
          display_name: string;
          base_url: string | null;
          env_key: string | null;
          default_model: string;
          openai_compatible: boolean;
          supports_model_list: boolean;
          docs_url: string;
          notes: string;
          has_credential: boolean;
        }>;
        count: number;
        default_provider: string;
        default_model: string;
        mock_mode: boolean;
      }>("/providers"),
    testProvider: (name: string) =>
      request<{ provider: string; ok: boolean; message: string; mock_mode: boolean }>(
        `/providers/test/${encodeURIComponent(name)}`,
        { method: "POST" },
      ),
    addCredential: (service: string, value: string) =>
      request<{ service: string; stored: boolean; mock_mode: boolean }>("/credentials", {
        method: "POST",
        body: JSON.stringify({ service, value }),
      }),
    removeCredential: (service: string) =>
      request<{ service: string; removed: boolean; mock_mode: boolean }>(
        `/credentials/${encodeURIComponent(service)}`,
        { method: "DELETE" },
      ),
    listCredentials: () =>
      request<{
        credentials: Array<{
          service: string;
          has_credential: boolean;
          preview: string | null;
        }>;
        count: number;
        mock_mode: boolean;
      }>("/credentials"),
  },

  // ---- Permissions (master prompt §9, §10, §55, §88) ----
  // Risk levels: low / medium / high / critical. Decisions: allow_once /
  // allow_for_workflow / always_allow. The policy endpoint exposes rate
  // limits + per-tool risk overrides (persisted to config/risk_overrides.json).
  permissions: {
    list: (profileId?: string) => {
      const qs = new URLSearchParams();
      if (profileId) qs.set("profile_id", profileId);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{ grants: Array<{ grant_id: string; tool: string; risk: string; decision: string; profile_id: string | null }>; count: number }>(
        `/permissions${suffix}`,
      );
    },
    grant: (body: { tool_name: string; risk_level: RiskLevel; decision?: string; profile_id?: string }) =>
      request<{ grant_id: string; tool_name: string; risk_level: string; decision: string; profile_id: string | null; granted: boolean }>(
        "/permissions",
        { method: "POST", body: JSON.stringify(body) },
      ),
    revoke: (grantId: string) =>
      request<{ grant_id: string; revoked: boolean }>(
        `/permissions/${encodeURIComponent(grantId)}`,
        { method: "DELETE" },
      ),
    riskLevels: () =>
      request<{
        levels: Array<{
          value: string;
          label: string;
          color: string;
          description: string;
          examples: string[];
        }>;
        count: number;
      }>("/permissions/risk-levels"),
    getPolicy: () =>
      request<{
        max_actions_per_minute: number;
        max_ai_calls_per_task: number;
        max_loops: number;
        max_file_operations: number;
        max_browser_tabs: number;
        risk_overrides: Record<string, string>;
      }>("/permissions/policy"),
    updatePolicy: (body: {
      max_actions_per_minute?: number;
      max_ai_calls_per_task?: number;
      max_loops?: number;
      max_file_operations?: number;
      max_browser_tabs?: number;
      risk_overrides?: Record<string, string>;
    }) =>
      request<{
        max_actions_per_minute: number;
        max_ai_calls_per_task: number;
        max_loops: number;
        max_file_operations: number;
        max_browser_tabs: number;
        risk_overrides: Record<string, string>;
      }>("/permissions/policy", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },

  // ---- Schedules (master prompt §24, §25) ----
  // Wraps the existing /schedules endpoints. Each schedule maps a workflow
  // to a trigger (schedule / file / application / browser / hotkey / webhook
  // / system / manual).
  schedules: {
    list: () =>
      request<Array<{ job_id: string; workflow_id: string | null; trigger_type: string; next_run_time: string | null; is_active: boolean | null }>>("/schedules"),
    triggers: () =>
      request<Array<{ type: string; description: string; required_fields: string[] }>>(
        "/schedules/triggers/types",
      ),
    create: (body: { workflow_id: string; trigger_config: Record<string, unknown> }) =>
      request<{ job_id: string }>("/schedules", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    remove: (jobId: string) =>
      request<{ job_id: string; unscheduled: boolean }>(
        `/schedules/${encodeURIComponent(jobId)}`,
        { method: "DELETE" },
      ),
    pause: (jobId: string) =>
      request<{ job_id: string; paused: boolean }>(
        `/schedules/${encodeURIComponent(jobId)}/pause`,
        { method: "POST" },
      ),
    resume: (jobId: string) =>
      request<{ job_id: string; resumed: boolean }>(
        `/schedules/${encodeURIComponent(jobId)}/resume`,
        { method: "POST" },
      ),
  },

  // ---- Agent (Phase 3 AI Computer Agent — master prompt §81) ----
  // Wraps the /agent/* endpoints. All calls honor mock mode + the
  // §86 minimum confidence threshold (returns found=false when below).
  agent: {
    observe: (body: { screenshot_path?: string }) =>
      request<{
        screenshot_path: string;
        active_app: string | null;
        active_window: string | null;
        ui_elements: Array<{
          text: string;
          type: string;
          bounding_box: { x: number; y: number; width: number; height: number };
          confidence: number;
        }>;
        text_on_screen: string[];
        ai_summary: string;
        observed_at: string;
      }>("/agent/observe", { method: "POST", body: JSON.stringify(body) }),

    findElement: (body: {
      description: string;
      screenshot_path?: string;
      browser_session_id?: string;
    }) =>
      request<{
        found: boolean;
        reason?: string;
        description?: string;
        location?: {
          x: number;
          y: number;
          width: number;
          height: number;
          confidence: number;
          method: string;
        };
      }>("/agent/find-element", { method: "POST", body: JSON.stringify(body) }),

    verifyAction: (body: { action: string; expected_result: string }) =>
      request<{
        verified: boolean;
        evidence: string;
        screenshot_path: string | null;
      }>("/agent/verify-action", { method: "POST", body: JSON.stringify(body) }),

    analyzeScreenshot: (body: { image_path: string; question?: string }) =>
      request<{
        description: string;
        elements: Array<unknown>;
        suggested_action: string | null;
        reasoning: string;
      }>("/agent/analyze-screenshot", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    compareScreenshots: (body: { before: string; after: string }) =>
      request<{
        changes: string[];
        new_elements: Array<unknown>;
        removed_elements: Array<unknown>;
        significant_change: boolean;
      }>("/agent/compare-screenshots", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    recover: (body: {
      failed_action: string;
      error?: string;
      screenshot_path?: string;
      step_context?: Record<string, unknown>;
      attempt_number?: number;
    }) =>
      request<{
        strategy: string;
        alternative_actions: string[];
        should_retry: boolean;
        should_skip: boolean;
        should_ask_user: boolean;
        reason: string;
        retry_delay_seconds: number;
      }>("/agent/recover", { method: "POST", body: JSON.stringify(body) }),

    executeAutonomously: (body: {
      goal: string;
      max_steps?: number;
      mode?: "assist" | "guided" | "autonomous";
    }) =>
      request<{
        goal: string;
        plan_id: string;
        mode: string;
        steps_executed: number;
        steps_succeeded: number;
        steps_failed: number;
        steps_skipped: number;
        duration_seconds: number;
        final_state: string;
        learnings: string[];
        execution_log: Array<{
          step_id: string;
          action: string;
          status: string;
          duration_ms?: number;
          error?: string | null;
          recovery_strategy?: string | null;
          observed_at?: string | null;
        }>;
        aborted: boolean;
        abort_reason?: string | null;
        started_at: string;
        finished_at?: string | null;
      }>("/agent/execute-autonomously", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    generateWorkflow: (body: { description: string }) =>
      request<{
        workflow: Workflow;
        executed: boolean;
      }>("/agent/generate-workflow", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    improveWorkflow: (body: { workflow_id: string; feedback: string }) =>
      request<{
        workflow: Workflow;
        saved: boolean;
      }>("/agent/improve-workflow", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    suggestions: () =>
      request<
        Array<{
          title: string;
          description: string;
          estimated_time_saved_per_week: string;
          proposed_workflow: Workflow;
        }>
      >("/agent/suggestions"),
  },

  // ---- Teams (Phase 4 — master prompt §82) ----
  // Wraps the /teams/* endpoints. Each team carries members, workspaces,
  // and enterprise policies. All write endpoints require an X-User-Id
  // header (the Electron shell injects this from the OS-level session).
  teams: {
    list: () =>
      request<{
        teams: Array<TeamSummary & { my_role?: string | null }>;
        count: number;
        mock_mode?: boolean;
      }>("/teams"),

    create: (body: {
      name: string;
      description?: string;
      max_members?: number;
      max_workflows?: number;
    }) =>
      request<TeamSummary>("/teams", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    get: (teamId: string) =>
      request<TeamSummary & { my_role?: string | null }>(
        `/teams/${encodeURIComponent(teamId)}`,
      ),

    update: (teamId: string, body: {
      name?: string;
      description?: string;
      max_members?: number;
      max_workflows?: number;
    }) =>
      request<TeamSummary>(`/teams/${encodeURIComponent(teamId)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),

    delete: (teamId: string) =>
      request<{ team_id: string; deleted: boolean }>(
        `/teams/${encodeURIComponent(teamId)}`,
        { method: "DELETE" },
      ),

    // Members
    listMembers: (teamId: string) =>
      request<{ members: TeamMember[]; count: number }>(
        `/teams/${encodeURIComponent(teamId)}/members`,
      ),

    inviteMember: (teamId: string, body: { email: string; role?: string }) =>
      request<TeamMember>(
        `/teams/${encodeURIComponent(teamId)}/members`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    updateMember: (
      teamId: string,
      userId: string,
      body: { role: string },
    ) =>
      request<TeamMember>(
        `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`,
        { method: "PUT", body: JSON.stringify(body) },
      ),

    removeMember: (teamId: string, userId: string) =>
      request<{ team_id: string; user_id: string; removed: boolean }>(
        `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`,
        { method: "DELETE" },
      ),

    // Workspaces
    listWorkspaces: (teamId: string) =>
      request<{ workspaces: Workspace[]; count: number }>(
        `/teams/${encodeURIComponent(teamId)}/workspaces`,
      ),

    createWorkspace: (
      teamId: string,
      body: { name: string; description?: string },
    ) =>
      request<Workspace>(
        `/teams/${encodeURIComponent(teamId)}/workspaces`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    // Policies
    listPolicies: (teamId: string) =>
      request<{ policies: EnterprisePolicy[]; count: number }>(
        `/teams/${encodeURIComponent(teamId)}/policies`,
      ),

    createPolicy: (
      teamId: string,
      body: {
        policy_type: string;
        policy_value?: unknown;
        enforced?: boolean;
      },
    ) =>
      request<EnterprisePolicy>(
        `/teams/${encodeURIComponent(teamId)}/policies`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    updatePolicy: (
      teamId: string,
      policyId: string,
      body: { policy_value?: unknown; enforced?: boolean },
    ) =>
      request<EnterprisePolicy>(
        `/teams/${encodeURIComponent(teamId)}/policies/${encodeURIComponent(policyId)}`,
        { method: "PUT", body: JSON.stringify(body) },
      ),

    deletePolicy: (teamId: string, policyId: string) =>
      request<{ policy_id: string; deleted: boolean }>(
        `/teams/${encodeURIComponent(teamId)}/policies/${encodeURIComponent(policyId)}`,
        { method: "DELETE" },
      ),
  },

  // ---- Analytics (Phase 4 — master prompt §82) ----
  // Execution analytics. Summary returns top-line metrics; events returns
  // the raw event stream; leaderboard returns top contributors; export
  // downloads CSV or JSON.
  analytics: {
    summary: (params?: {
      team_id?: string;
      date_from?: string;
      date_to?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params?.team_id) qs.set("team_id", params.team_id);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<AnalyticsSummary>(`/analytics/summary${suffix}`);
    },

    events: (params?: {
      team_id?: string;
      user_id?: string;
      event_type?: string;
      date_from?: string;
      date_to?: string;
      limit?: number;
      offset?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.team_id) qs.set("team_id", params.team_id);
      if (params?.user_id) qs.set("user_id", params.user_id);
      if (params?.event_type) qs.set("event_type", params.event_type);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      if (params?.offset !== undefined) qs.set("offset", String(params.offset));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{ events: AnalyticsEvent[]; count: number; total: number }>(
        `/analytics/events${suffix}`,
      );
    },

    leaderboard: (params?: { team_id?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.team_id) qs.set("team_id", params.team_id);
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return request<{
        leaderboard: Array<{ user_id: string; activity_count: number }>;
        count: number;
      }>(`/analytics/leaderboard${suffix}`);
    },

    export: (params: {
      format: "json" | "csv";
      team_id?: string;
      date_from?: string;
      date_to?: string;
    }): Promise<Blob> => {
      const qs = new URLSearchParams();
      qs.set("format", params.format);
      if (params.team_id) qs.set("team_id", params.team_id);
      if (params.date_from) qs.set("date_from", params.date_from);
      if (params.date_to) qs.set("date_to", params.date_to);
      return fetch(`${BASE_URL}/analytics/export?${qs.toString()}`).then((r) => {
        if (!r.ok) {
          return r.json().catch(() => ({ detail: r.statusText })).then((body) => {
            throw new Error(`${r.status}: ${body.detail || "export failed"}`);
          });
        }
        return r.blob();
      });
    },
  },
};

// ---------------------------------------------------------------------------
// Phase 4 type declarations (master prompt §82)
// ---------------------------------------------------------------------------

export interface TeamSummary {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  owner_id: string;
  max_members: number;
  max_workflows: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TeamMember {
  id?: string;
  team_id: string;
  user_id: string;
  email?: string | null;
  role: string; // owner | admin | member | viewer
  status: string; // pending | active | revoked
  invited_at?: string | null;
  joined_at?: string | null;
}

export interface Workspace {
  id: string;
  team_id: string;
  name: string;
  description?: string | null;
  created_by: string;
  created_at?: string | null;
}

export interface EnterprisePolicy {
  id: string;
  team_id: string;
  policy_type: string;
  policy_value?: unknown;
  enforced: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AnalyticsSummary {
  total_workflows_run: number;
  success_rate: number;
  avg_duration_ms: number;
  total_ai_calls: number;
  estimated_cost: number;
  top_tools: Array<{ tool: string; count: number; avg_duration_ms: number }>;
  top_workflows: Array<{
    workflow: string;
    runs: number;
    success_rate: number;
  }>;
  daily_breakdown: Array<{
    date: string;
    runs: number;
    successes: number;
    failures: number;
  }>;
  filters: {
    team_id?: string | null;
    user_id?: string | null;
    date_from?: string | null;
    date_to?: string | null;
  };
  mock_mode: boolean;
}

export interface AnalyticsEvent {
  id: number;
  team_id?: string | null;
  user_id?: string | null;
  event_type: string;
  event_data?: Record<string, unknown> | null;
  duration_ms?: number | null;
  cost_estimate?: number | null;
  created_at?: string | null;
}

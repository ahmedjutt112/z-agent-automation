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
};

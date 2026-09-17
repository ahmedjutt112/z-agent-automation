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

  emergencyStop: () =>
    request<{ engaged: boolean }>("/emergency-stop", { method: "POST" }),
  emergencyReset: () =>
    request<{ engaged: boolean }>("/emergency-reset", { method: "POST" }),

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
};

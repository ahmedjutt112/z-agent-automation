/**
 * Automation API client — typed wrappers around fetch() to the Python service.
 * Master prompt §75 — typed API contract.
 */

const BASE_URL = "http://127.0.0.1:8765";

export interface ToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  permission_level: string;
  risk_level: "low" | "medium" | "high" | "critical";
  timeout_ms: number;
  rollback_strategy?: string | null;
  verification_strategy?: string | null;
}

export interface PlanStep {
  id: string;
  action: string;
  args: Record<string, unknown>;
  risk_level: "low" | "medium" | "high" | "critical";
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
  overall_risk: "low" | "medium" | "high" | "critical";
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

  listWorkflows: () => request<WorkflowSummary[]>("/workflow"),

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
};

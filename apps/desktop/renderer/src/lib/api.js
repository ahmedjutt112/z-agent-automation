/**
 * Automation API client — typed wrappers around fetch() to the Python service.
 * Master prompt §75 — typed API contract.
 *
 * BASE_URL is configurable via Vite env var VITE_API_URL (defaults to localhost
 * for dev; set to your deployed backend URL for production).
 */
const BASE_URL = import.meta.env?.VITE_API_URL || "http://127.0.0.1:8765";
async function request(path, init) {
    const resp = await fetch(`${BASE_URL}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(`${resp.status}: ${body.detail || "request failed"}`);
    }
    return await resp.json();
}
export const api = {
    health: () => request("/health"),
    listTools: () => request("/tools"),
    createPlan: (goal) => request(`/task/plan?goal=${encodeURIComponent(goal)}`, { method: "POST" }),
    runPlan: (plan, mode = "guided") => request("/task/run", {
        method: "POST",
        body: JSON.stringify({ ...plan, mode }),
    }),
    cancelRun: (runId) => request(`/task/cancel/${runId}`, { method: "POST" }),
    // ---- Workflow CRUD (master prompt §21, §34) ----
    listWorkflows: () => request("/workflow"),
    /** POST /workflow — save a new workflow (or overwrite by id). */
    saveWorkflow: (workflow) => request("/workflow", {
        method: "POST",
        body: JSON.stringify(workflow),
    }),
    /** GET /workflow/{id} — full workflow object. */
    getWorkflow: (id) => request(`/workflow/${encodeURIComponent(id)}`),
    /** PUT /workflow/{id} — partial update (server bumps version on node changes). */
    updateWorkflow: (id, workflow) => request(`/workflow/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(workflow) }),
    /** DELETE /workflow/{id} */
    deleteWorkflow: (id) => request(`/workflow/${encodeURIComponent(id)}`, { method: "DELETE" }),
    /** POST /workflow/{id}/duplicate */
    duplicateWorkflow: (id) => request(`/workflow/${encodeURIComponent(id)}/duplicate`, { method: "POST" }),
    /** GET /workflow/{id}/versions */
    listWorkflowVersions: (id) => request(`/workflow/${encodeURIComponent(id)}/versions`),
    /** POST /workflow/{id}/run — executes a saved workflow via WorkflowExecutor. */
    runWorkflow: (id) => request(`/workflow/${encodeURIComponent(id)}/run`, { method: "POST" }),
    /** GET /workflow/templates — built-in starter workflows. */
    listWorkflowTemplates: () => request("/workflow/templates"),
    // ---- Workflow import / export / validate / permissions (§51) ----
    /**
     * POST /workflow/import — validates + imports a workflow JSON.
     * The imported workflow is saved with enabled=false (master prompt §51:
     * "Never execute imported workflows automatically"). The response
     * includes the permissions_required + risk_level so the UI can show a
     * permission-review modal before the user enables it.
     */
    importWorkflow: (workflowJson, profileId) => request("/workflow/import", {
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
    exportWorkflow: (id) => fetch(`${BASE_URL}/workflow/${encodeURIComponent(id)}/export`).then((r) => {
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
    validateWorkflow: (workflowJson) => request("/workflow/validate", {
        method: "POST",
        body: JSON.stringify({ workflow_json: workflowJson }),
    }),
    /**
     * GET /workflow/{id}/permissions — returns the permissions required by
     * this workflow (master prompt §51: "Show permission requirements before
     * execution").
     */
    workflowPermissions: (id) => request(`/workflow/${encodeURIComponent(id)}/permissions`),
    // ---- Logs (master prompt §38, §57, §73) ----
    // The /logs/stream WebSocket is opened directly by the renderer (see
    // DevPanel.tsx); these helpers cover the HTTP surface.
    logs: {
        /** GET /logs/recent — last N entries, optionally filtered. */
        recent: (limit = 100, level, tool, taskId) => {
            const params = new URLSearchParams({ limit: String(limit) });
            if (level)
                params.set("level", level);
            if (tool)
                params.set("tool", tool);
            if (taskId)
                params.set("task_id", taskId);
            return request(`/logs/recent?${params.toString()}`);
        },
        /** GET /logs/export?format=...&since=... — returns a Blob (json|csv|txt). */
        exportLogs: (format, since, level, tool, taskId) => {
            const params = new URLSearchParams({ format });
            if (since)
                params.set("since", since);
            if (level)
                params.set("level", level);
            if (tool)
                params.set("tool", tool);
            if (taskId)
                params.set("task_id", taskId);
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
        list: (limit = 50, taskId, profileId) => {
            const params = new URLSearchParams({ limit: String(limit) });
            if (taskId)
                params.set("task_id", taskId);
            if (profileId)
                params.set("profile_id", profileId);
            return request(`/screenshots?${params.toString()}`);
        },
        /** GET /screenshots/{id} — raw PNG bytes. */
        get: (id) => fetch(`${BASE_URL}/screenshots/${encodeURIComponent(id)}`).then((r) => {
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
        metadata: (id) => request(`/screenshots/${encodeURIComponent(id)}/metadata`),
        /** DELETE /screenshots/{id} — removes the file + DB row. */
        delete: (id) => request(`/screenshots/${encodeURIComponent(id)}`, {
            method: "DELETE",
        }),
        /** POST /screenshots/{id}/ocr — runs OCR, returns text + bounding boxes. */
        ocr: (id) => request(`/screenshots/${encodeURIComponent(id)}/ocr`, {
            method: "POST",
        }),
    },
    emergencyStop: () => request("/emergency-stop", { method: "POST" }),
    emergencyReset: () => request("/emergency-reset", { method: "POST" }),
    // ---- Marketplace (master prompt §52 — template marketplace) ----
    // Imported workflows MUST be sandboxed + permission-scanned (§51).
    // The install endpoint returns the workflow with enabled=false so the
    // user must manually enable it before any node can run.
    marketplace: {
        /** GET /marketplace/templates — list templates, optionally filtered. */
        listTemplates: (params) => {
            const qs = new URLSearchParams();
            if (params?.category)
                qs.set("category", params.category);
            if (params?.tag)
                qs.set("tag", params.tag);
            if (params?.limit)
                qs.set("limit", String(params.limit));
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/marketplace/templates${suffix}`);
        },
        /** GET /marketplace/templates/{id} — full template (incl. workflow). */
        getTemplate: (id) => request(`/marketplace/templates/${encodeURIComponent(id)}`),
        /** GET /marketplace/search?q=... — free-text search. */
        searchTemplates: (q) => request(`/marketplace/search?q=${encodeURIComponent(q)}`),
        /**
         * POST /marketplace/install/{id} — installs the template as a user
         * workflow. The workflow is saved with enabled=false; the response
         * includes permissions_required + risk_level + warnings so the UI
         * can render a permission-review modal before the user enables it.
         */
        installTemplate: (id, profileId) => request(`/marketplace/install/${encodeURIComponent(id)}`, {
            method: "POST",
            body: JSON.stringify({ profile_id: profileId ?? null }),
        }),
        /** DELETE /marketplace/install/{id} — uninstalls the workflow. */
        uninstallTemplate: (id, profileId) => request(`/marketplace/install/${encodeURIComponent(id)}`, {
            method: "DELETE",
            body: JSON.stringify({ profile_id: profileId ?? null }),
        }),
        /** POST /marketplace/rate/{id} — add a 1-5 star rating. */
        rateTemplate: (id, rating) => request(`/marketplace/rate/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ rating }) }),
        /** POST /marketplace/submit — publish a user-submitted template. */
        submitTemplate: (body) => request("/marketplace/submit", { method: "POST", body: JSON.stringify(body) }),
        /** GET /marketplace/categories — list every category with counts. */
        listCategories: () => request("/marketplace/categories"),
        /** GET /marketplace/featured — 6 featured templates. */
        getFeatured: () => request("/marketplace/featured"),
    },
    // ---- OAuth (master prompt §54) ----
    oauth: {
        start: (provider) => request(`/oauth/${encodeURIComponent(provider)}/start`),
        status: () => request("/oauth/status"),
        disconnect: (provider) => request(`/oauth/${encodeURIComponent(provider)}/disconnect`, { method: "POST" }),
    },
    // ---- Messaging integrations (master prompt §54) ----
    integrations: {
        list: () => request("/integrations"),
        sendEmail: (to, subject, body, html = false) => request("/integrations/email/send", { method: "POST", body: JSON.stringify({ to, subject, body, html }) }),
        emailInbox: (limit = 10) => request(`/integrations/email/inbox?limit=${limit}`),
        sendWhatsApp: (to, message) => request("/integrations/whatsapp/send-text", { method: "POST", body: JSON.stringify({ to, message }) }),
        sendTelegram: (chat_id, text, parse_mode = "HTML") => request("/integrations/telegram/send", { method: "POST", body: JSON.stringify({ chat_id, text, parse_mode }) }),
        sendDiscord: (channel_id, content) => request("/integrations/discord/send", { method: "POST", body: JSON.stringify({ channel_id, content }) }),
    },
    // ---- Voice control (master prompt section 46) ----
    // Pipeline: Microphone -> STT -> AI Planner -> Permission Engine -> Automation
    // CRITICAL: voice commands NEVER bypass security confirmation.
    // listenAndPlan returns the plan WITHOUT executing it; the frontend
    // must display it and require the user to click "Approve & Run"
    // before calling listenAndExecute.
    voice: {
        /** POST /voice/listen — capture + transcribe a single utterance. */
        listen: () => request("/voice/listen", { method: "POST" }),
        /** POST /voice/speak — synthesize + play TTS audio. */
        speak: (text, voice = "default") => request("/voice/speak", {
            method: "POST",
            body: JSON.stringify({ text, voice }),
        }),
        /**
         * POST /voice/listen-and-plan — full pipeline up to plan generation.
         * Returns {transcript, plan} WITHOUT executing the plan.
         * The frontend MUST display the plan and require explicit user
         * approval before calling listenAndExecute.
         */
        listenAndPlan: () => request("/voice/listen-and-plan", { method: "POST" }),
        /**
         * POST /voice/listen-and-execute — execute an already-approved plan
         * via WorkflowExecutor. The permission engine is re-evaluated
         * (defense in depth) before execution begins.
         */
        listenAndExecute: (plan) => request("/voice/listen-and-execute", { method: "POST", body: JSON.stringify({ plan }) }),
        /** POST /voice/start-continuous — start background wake-word listening. */
        startContinuous: () => request("/voice/start-continuous", { method: "POST" }),
        /** POST /voice/stop-continuous — stop background listening. */
        stopContinuous: () => request("/voice/stop-continuous", { method: "POST" }),
        /** GET /voice/status — current voice subsystem status. */
        status: () => request("/voice/status"),
    },
    // ---- AI Assistant (master prompt §83 — Phase 5) ----
    // High-level contextual automation: prepare-meeting, morning routine,
    // end-of-day summary, research, file organisation, calendar lookup.
    // CRITICAL: every plan-returning endpoint returns executed=false; the
    // frontend MUST display the plan and require explicit user approval
    // before calling runMeetingPrep (or /task/run).
    assistant: {
        /** POST /assistant/prepare-meeting — generate a meeting-prep Plan. */
        prepareMeeting: (meetingId) => request("/assistant/prepare-meeting", {
            method: "POST",
            body: JSON.stringify({ meeting_id: meetingId ?? null }),
        }),
        /** POST /assistant/run-meeting-prep — execute an approved plan. */
        runMeetingPrep: (plan) => request("/assistant/run-meeting-prep", { method: "POST", body: JSON.stringify({ plan }) }),
        /** POST /assistant/organize-files — generate a file-organisation Plan. */
        organizeFiles: (context) => request("/assistant/organize-files", {
            method: "POST",
            body: JSON.stringify({ context }),
        }),
        /** POST /assistant/morning-routine — generate a morning-routine Plan. */
        morningRoutine: () => request("/assistant/morning-routine", {
            method: "POST",
        }),
        /** GET /assistant/end-of-day-summary — summary of today's activities. */
        endOfDaySummary: () => request("/assistant/end-of-day-summary"),
        /** POST /assistant/research — generate a research Plan. */
        research: (topic, depth = 3) => request("/assistant/research", {
            method: "POST",
            body: JSON.stringify({ topic, depth }),
        }),
        /** GET /assistant/calendar/next-meeting — the next upcoming event. */
        nextMeeting: () => request("/assistant/calendar/next-meeting"),
        /** GET /assistant/calendar/events — list events in a window. */
        calendarEvents: (params) => {
            const qs = new URLSearchParams();
            if (params?.time_min)
                qs.set("time_min", params.time_min);
            if (params?.time_max)
                qs.set("time_max", params.time_max);
            if (params?.max_results)
                qs.set("max_results", String(params.max_results));
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/assistant/calendar/events${suffix}`);
        },
    },
    // ---- Task Recorder (master prompt §22, §35) ----
    // Captures raw mouse / keyboard / browser / file events and compiles them
    // into a Workflow. The backend TaskRecorder is in mock_mode by default —
    // start() just flips a flag and stop() returns a fake Recording with 3-4
    // sample events so the to-workflow pipeline can be exercised.
    recorder: {
        start: () => request("/recorder/start", { method: "POST" }),
        pause: () => request("/recorder/pause", { method: "POST" }),
        resume: () => request("/recorder/resume", { method: "POST" }),
        stop: () => request("/recorder/stop", { method: "POST" }),
        status: () => request("/recorder/status"),
        events: () => request("/recorder/events"),
        toWorkflow: (name) => request("/recorder/to-workflow", { method: "POST", body: JSON.stringify({ name: name ?? null }) }),
        deleteEvent: (index) => request(`/recorder/events/${index}`, { method: "DELETE" }),
    },
    // ---- Browser sessions (master prompt §16, §17) ----
    // In mock mode the underlying Playwright instance is never started —
    // the routes still record session metadata so the UI's session list works.
    browser: {
        listSessions: () => request("/browser/sessions"),
        createSession: (body) => request("/browser/session", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        closeSession: (sessionId) => request(`/browser/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
        navigate: (sessionId, url) => request(`/browser/session/${encodeURIComponent(sessionId)}/navigate`, { method: "POST", body: JSON.stringify({ url }) }),
        click: (sessionId, selector) => request(`/browser/session/${encodeURIComponent(sessionId)}/click`, { method: "POST", body: JSON.stringify({ selector }) }),
        type: (sessionId, selector, text) => request(`/browser/session/${encodeURIComponent(sessionId)}/type`, { method: "POST", body: JSON.stringify({ selector, text }) }),
        extract: (sessionId, selector) => request(`/browser/session/${encodeURIComponent(sessionId)}/extract`, { method: "POST", body: JSON.stringify({ selector }) }),
        screenshot: (sessionId) => request(`/browser/session/${encodeURIComponent(sessionId)}/screenshot`, { method: "POST" }),
    },
    // ---- Files (master prompt §18, §55 File Security) ----
    // Every path goes through the backend _validate_path allowlist. Blocked
    // paths (/etc, /usr, C:/Windows etc.) return 403. file.delete is CRITICAL
    // risk — pass approved=true after the user confirms.
    files: {
        list: (path, pattern = "*") => request(`/files/list?path=${encodeURIComponent(path)}&pattern=${encodeURIComponent(pattern)}`),
        read: (path, encoding = "utf-8", maxBytes = 1_048_576) => request(`/files/read?path=${encodeURIComponent(path)}&encoding=${encodeURIComponent(encoding)}&max_bytes=${maxBytes}`),
        write: (path, content, encoding = "utf-8") => request("/files/write", {
            method: "POST",
            body: JSON.stringify({ path, content, encoding }),
        }),
        move: (source, destination) => request("/files/move", {
            method: "POST",
            body: JSON.stringify({ source, destination }),
        }),
        rename: (path, newName) => request("/files/rename", {
            method: "POST",
            body: JSON.stringify({ path, new_name: newName }),
        }),
        copy: (source, destination) => request("/files/copy", {
            method: "POST",
            body: JSON.stringify({ source, destination }),
        }),
        delete: (path, approved) => request("/files/delete", {
            method: "POST",
            body: JSON.stringify({ path, approved }),
        }),
        download: (path) => fetch(`${BASE_URL}/files/download?path=${encodeURIComponent(path)}`).then((r) => {
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
        listTasks: (params) => {
            const qs = new URLSearchParams();
            if (params?.limit !== undefined)
                qs.set("limit", String(params.limit));
            if (params?.offset !== undefined)
                qs.set("offset", String(params.offset));
            if (params?.status)
                qs.set("status", params.status);
            if (params?.date_from)
                qs.set("date_from", params.date_from);
            if (params?.date_to)
                qs.set("date_to", params.date_to);
            if (params?.search)
                qs.set("search", params.search);
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/history/tasks${suffix}`);
        },
        getTask: (taskId) => request(`/history/tasks/${encodeURIComponent(taskId)}`),
        getTaskScreenshots: (taskId) => request(`/history/tasks/${encodeURIComponent(taskId)}/screenshots`),
        getTaskLogs: (taskId) => request(`/history/tasks/${encodeURIComponent(taskId)}/logs`),
        rerunTask: (taskId) => request(`/history/tasks/${encodeURIComponent(taskId)}/rerun`, { method: "POST" }),
        export: (params) => {
            const qs = new URLSearchParams();
            if (params?.status)
                qs.set("status", params.status);
            if (params?.date_from)
                qs.set("date_from", params.date_from);
            if (params?.date_to)
                qs.set("date_to", params.date_to);
            if (params?.search)
                qs.set("search", params.search);
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
        list: (provider) => {
            const qs = new URLSearchParams();
            if (provider)
                qs.set("provider", provider);
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/ai-models${suffix}`);
        },
        sync: (provider) => {
            const qs = new URLSearchParams();
            if (provider)
                qs.set("provider", provider);
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/ai-models/sync${suffix}`, { method: "POST" });
        },
        listProviders: () => request("/providers"),
        testProvider: (name) => request(`/providers/test/${encodeURIComponent(name)}`, { method: "POST" }),
        addCredential: (service, value) => request("/credentials", {
            method: "POST",
            body: JSON.stringify({ service, value }),
        }),
        removeCredential: (service) => request(`/credentials/${encodeURIComponent(service)}`, { method: "DELETE" }),
        listCredentials: () => request("/credentials"),
    },
    // ---- Permissions (master prompt §9, §10, §55, §88) ----
    // Risk levels: low / medium / high / critical. Decisions: allow_once /
    // allow_for_workflow / always_allow. The policy endpoint exposes rate
    // limits + per-tool risk overrides (persisted to config/risk_overrides.json).
    permissions: {
        list: (profileId) => {
            const qs = new URLSearchParams();
            if (profileId)
                qs.set("profile_id", profileId);
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/permissions${suffix}`);
        },
        grant: (body) => request("/permissions", { method: "POST", body: JSON.stringify(body) }),
        revoke: (grantId) => request(`/permissions/${encodeURIComponent(grantId)}`, { method: "DELETE" }),
        riskLevels: () => request("/permissions/risk-levels"),
        getPolicy: () => request("/permissions/policy"),
        updatePolicy: (body) => request("/permissions/policy", {
            method: "PUT",
            body: JSON.stringify(body),
        }),
    },
    // ---- Schedules (master prompt §24, §25) ----
    // Wraps the existing /schedules endpoints. Each schedule maps a workflow
    // to a trigger (schedule / file / application / browser / hotkey / webhook
    // / system / manual).
    schedules: {
        list: () => request("/schedules"),
        triggers: () => request("/schedules/triggers/types"),
        create: (body) => request("/schedules", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        remove: (jobId) => request(`/schedules/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
        pause: (jobId) => request(`/schedules/${encodeURIComponent(jobId)}/pause`, { method: "POST" }),
        resume: (jobId) => request(`/schedules/${encodeURIComponent(jobId)}/resume`, { method: "POST" }),
    },
    // ---- Agent (Phase 3 AI Computer Agent — master prompt §81) ----
    // Wraps the /agent/* endpoints. All calls honor mock mode + the
    // §86 minimum confidence threshold (returns found=false when below).
    agent: {
        observe: (body) => request("/agent/observe", { method: "POST", body: JSON.stringify(body) }),
        findElement: (body) => request("/agent/find-element", { method: "POST", body: JSON.stringify(body) }),
        verifyAction: (body) => request("/agent/verify-action", { method: "POST", body: JSON.stringify(body) }),
        analyzeScreenshot: (body) => request("/agent/analyze-screenshot", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        compareScreenshots: (body) => request("/agent/compare-screenshots", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        recover: (body) => request("/agent/recover", { method: "POST", body: JSON.stringify(body) }),
        executeAutonomously: (body) => request("/agent/execute-autonomously", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        generateWorkflow: (body) => request("/agent/generate-workflow", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        improveWorkflow: (body) => request("/agent/improve-workflow", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        suggestions: () => request("/agent/suggestions"),
    },
    // ---- Teams (Phase 4 — master prompt §82) ----
    // Wraps the /teams/* endpoints. Each team carries members, workspaces,
    // and enterprise policies. All write endpoints require an X-User-Id
    // header (the Electron shell injects this from the OS-level session).
    teams: {
        list: () => request("/teams"),
        create: (body) => request("/teams", {
            method: "POST",
            body: JSON.stringify(body),
        }),
        get: (teamId) => request(`/teams/${encodeURIComponent(teamId)}`),
        update: (teamId, body) => request(`/teams/${encodeURIComponent(teamId)}`, {
            method: "PUT",
            body: JSON.stringify(body),
        }),
        delete: (teamId) => request(`/teams/${encodeURIComponent(teamId)}`, { method: "DELETE" }),
        // Members
        listMembers: (teamId) => request(`/teams/${encodeURIComponent(teamId)}/members`),
        inviteMember: (teamId, body) => request(`/teams/${encodeURIComponent(teamId)}/members`, { method: "POST", body: JSON.stringify(body) }),
        updateMember: (teamId, userId, body) => request(`/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`, { method: "PUT", body: JSON.stringify(body) }),
        removeMember: (teamId, userId) => request(`/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" }),
        // Workspaces
        listWorkspaces: (teamId) => request(`/teams/${encodeURIComponent(teamId)}/workspaces`),
        createWorkspace: (teamId, body) => request(`/teams/${encodeURIComponent(teamId)}/workspaces`, { method: "POST", body: JSON.stringify(body) }),
        // Policies
        listPolicies: (teamId) => request(`/teams/${encodeURIComponent(teamId)}/policies`),
        createPolicy: (teamId, body) => request(`/teams/${encodeURIComponent(teamId)}/policies`, { method: "POST", body: JSON.stringify(body) }),
        updatePolicy: (teamId, policyId, body) => request(`/teams/${encodeURIComponent(teamId)}/policies/${encodeURIComponent(policyId)}`, { method: "PUT", body: JSON.stringify(body) }),
        deletePolicy: (teamId, policyId) => request(`/teams/${encodeURIComponent(teamId)}/policies/${encodeURIComponent(policyId)}`, { method: "DELETE" }),
    },
    // ---- Analytics (Phase 4 — master prompt §82) ----
    // Execution analytics. Summary returns top-line metrics; events returns
    // the raw event stream; leaderboard returns top contributors; export
    // downloads CSV or JSON.
    analytics: {
        summary: (params) => {
            const qs = new URLSearchParams();
            if (params?.team_id)
                qs.set("team_id", params.team_id);
            if (params?.date_from)
                qs.set("date_from", params.date_from);
            if (params?.date_to)
                qs.set("date_to", params.date_to);
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/analytics/summary${suffix}`);
        },
        events: (params) => {
            const qs = new URLSearchParams();
            if (params?.team_id)
                qs.set("team_id", params.team_id);
            if (params?.user_id)
                qs.set("user_id", params.user_id);
            if (params?.event_type)
                qs.set("event_type", params.event_type);
            if (params?.date_from)
                qs.set("date_from", params.date_from);
            if (params?.date_to)
                qs.set("date_to", params.date_to);
            if (params?.limit !== undefined)
                qs.set("limit", String(params.limit));
            if (params?.offset !== undefined)
                qs.set("offset", String(params.offset));
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/analytics/events${suffix}`);
        },
        leaderboard: (params) => {
            const qs = new URLSearchParams();
            if (params?.team_id)
                qs.set("team_id", params.team_id);
            if (params?.limit !== undefined)
                qs.set("limit", String(params.limit));
            const suffix = qs.toString() ? `?${qs.toString()}` : "";
            return request(`/analytics/leaderboard${suffix}`);
        },
        export: (params) => {
            const qs = new URLSearchParams();
            qs.set("format", params.format);
            if (params.team_id)
                qs.set("team_id", params.team_id);
            if (params.date_from)
                qs.set("date_from", params.date_from);
            if (params.date_to)
                qs.set("date_to", params.date_to);
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

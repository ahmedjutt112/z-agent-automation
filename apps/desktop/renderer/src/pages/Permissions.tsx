/**
 * Permissions page — master prompt §9 (risk levels), §10 (human confirmation),
 * §55 (security architecture), §88 (rate limits).
 *
 * Three panels:
 * 1. Risk level reference — 4 cards (low / medium / high / critical) with
 *    examples.
 * 2. Granted permissions — list of grants with revoke buttons + a
 *    "Grant Permission" form.
 * 3. Risk policy editor — rate limits (max_actions_per_minute, ...) + per-tool
 *    risk overrides + emergency stop config.
 */

import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import type { RiskLevel } from "../lib/api";

interface RiskLevelInfo {
  value: string;
  label: string;
  color: string;
  description: string;
  examples: string[];
}

interface PermissionGrant {
  grant_id: string;
  tool: string;
  risk: string;
  decision: string;
  profile_id: string | null;
}

interface ToolSpec {
  name: string;
  risk_level: RiskLevel;
}

interface PolicyState {
  max_actions_per_minute: number;
  max_ai_calls_per_task: number;
  max_loops: number;
  max_file_operations: number;
  max_browser_tabs: number;
  risk_overrides: Record<string, string>;
}

const COLOR_CLASSES: Record<string, string> = {
  green: "bg-emerald-500/10 border-emerald-700 text-emerald-300",
  yellow: "bg-yellow-500/10 border-yellow-700 text-yellow-300",
  orange: "bg-orange-500/10 border-orange-700 text-orange-300",
  red: "bg-red-500/10 border-red-700 text-red-300",
};

export function Permissions() {
  const mockMode = useStore((s) => s.mockMode);
  const [levels, setLevels] = useState<RiskLevelInfo[]>([]);
  const [grants, setGrants] = useState<PermissionGrant[]>([]);
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [policy, setPolicy] = useState<PolicyState | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    setStatus("loading");
    setError("");
    try {
      const [lv, gr, ts, pol] = await Promise.all([
        api.permissions.riskLevels(),
        api.permissions.list(),
        api.listTools(),
        api.permissions.getPolicy(),
      ]);
      setLevels(lv.levels);
      setGrants(gr.grants as PermissionGrant[]);
      setTools(ts);
      setPolicy(pol);
      setStatus("ready");
    } catch (e) {
      setError(String(e));
      setStatus("error");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function revoke(grantId: string) {
    if (!window.confirm("Revoke this permission?")) return;
    try {
      await api.permissions.revoke(grantId);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function savePolicy(next: PolicyState) {
    setError("");
    try {
      await api.permissions.updatePolicy({
        max_actions_per_minute: next.max_actions_per_minute,
        max_ai_calls_per_task: next.max_ai_calls_per_task,
        max_loops: next.max_loops,
        max_file_operations: next.max_file_operations,
        max_browser_tabs: next.max_browser_tabs,
        risk_overrides: next.risk_overrides,
      });
      setPolicy(next);
      setMessage("Policy saved.");
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Permissions</h1>
          <p className="text-zinc-400 mt-1">
            Risk levels, granted permissions, and rate-limit policy.
          </p>
        </div>
        <button
          onClick={refresh}
          className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5 text-sm"
        >
          Refresh
        </button>
      </div>

      {mockMode && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 text-sm text-amber-300">
          Permission engine is in mock mode — grants are stored in memory only
          and lost on service restart.
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {message && (
        <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-zinc-200">
          {message}
        </div>
      )}

      {/* 1. Risk level reference */}
      <div>
        <h2 className="text-sm uppercase tracking-wider text-zinc-500 mb-2">
          Risk Levels
        </h2>
        <div className="grid grid-cols-4 gap-3">
          {levels.length === 0 ? (
            <div className="col-span-4 text-zinc-500 text-sm">Loading...</div>
          ) : (
            levels.map((lv) => (
              <div
                key={lv.value}
                className={`border rounded-lg p-3 ${COLOR_CLASSES[lv.color] ?? "border-zinc-700 text-zinc-300"}`}
              >
                <div className="text-sm font-medium uppercase">{lv.label}</div>
                <div className="text-xs mt-1 opacity-80">{lv.description}</div>
                <div className="mt-2 text-xs">
                  <div className="opacity-60">Examples:</div>
                  <ul className="mt-0.5 font-mono space-y-0.5">
                    {lv.examples.map((ex) => (
                      <li key={ex}>{ex}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* 2. Granted permissions */}
        <div className="col-span-7">
          <GrantForm
            tools={tools}
            levels={levels}
            onGranted={() => refresh()}
          />
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg mt-3">
            <div className="px-4 py-3 border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
              Granted Permissions ({grants.length})
            </div>
            <div className="divide-y divide-zinc-800">
              {grants.length === 0 ? (
                <div className="px-4 py-8 text-center text-zinc-500 text-sm">
                  No grants. Use the form above to grant one.
                </div>
              ) : (
                grants.map((g) => (
                  <div
                    key={g.grant_id}
                    className="px-4 py-2 flex items-center justify-between"
                  >
                    <div>
                      <div className="text-sm font-mono">{g.tool}</div>
                      <div className="text-xs text-zinc-500 mt-0.5 flex gap-3">
                        <span>risk: {g.risk}</span>
                        <span>decision: {g.decision}</span>
                        <span>profile: {g.profile_id ?? "global"}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => revoke(g.grant_id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Revoke
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* 3. Risk policy editor */}
        <div className="col-span-5">
          {policy && (
            <PolicyEditor policy={policy} onSave={savePolicy} />
          )}
        </div>
      </div>
    </div>
  );
}

function GrantForm({
  tools,
  levels,
  onGranted,
}: {
  tools: ToolSpec[];
  levels: RiskLevelInfo[];
  onGranted: () => void;
}) {
  const [toolName, setToolName] = useState("");
  const [risk, setRisk] = useState<RiskLevel>("low");
  const [decision, setDecision] = useState("allow_for_workflow");
  const [profileId, setProfileId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.permissions.grant({
        tool_name: toolName,
        risk_level: risk,
        decision,
        profile_id: profileId || undefined,
      });
      setToolName("");
      onGranted();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3"
    >
      <div className="text-xs uppercase tracking-wider text-zinc-500">
        Grant Permission
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-500">Tool</label>
          <select
            value={toolName}
            onChange={(e) => setToolName(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            required
          >
            <option value="">Select a tool...</option>
            {tools.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.risk_level})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500">Risk Level</label>
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value as RiskLevel)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500">Decision</label>
          <select
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="allow_once">allow_once</option>
            <option value="allow_for_workflow">allow_for_workflow</option>
            <option value="always_allow">always_allow</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500">Profile ID (optional)</label>
          <input
            value={profileId}
            onChange={(e) => setProfileId(e.target.value)}
            placeholder="(global)"
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          />
        </div>
      </div>
      {error && <div className="text-xs text-red-400">{error}</div>}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={busy || !toolName}
          className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Granting..." : "Grant"}
        </button>
      </div>
    </form>
  );
}

function PolicyEditor({
  policy,
  onSave,
}: {
  policy: PolicyState;
  onSave: (next: PolicyState) => void;
}) {
  const [draft, setDraft] = useState<PolicyState>(policy);
  const [overrideTool, setOverrideTool] = useState("");
  const [overrideRisk, setOverrideRisk] = useState("critical");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDraft(policy);
  }, [policy]);

  function setField<K extends keyof PolicyState>(key: K, value: PolicyState[K]) {
    setDraft({ ...draft, [key]: value });
  }

  function addOverride() {
    if (!overrideTool) return;
    setDraft({
      ...draft,
      risk_overrides: { ...draft.risk_overrides, [overrideTool]: overrideRisk },
    });
    setOverrideTool("");
  }

  function removeOverride(tool: string) {
    const next = { ...draft.risk_overrides };
    delete next[tool];
    setDraft({ ...draft, risk_overrides: next });
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
      <div className="text-xs uppercase tracking-wider text-zinc-500">
        Risk Policy & Rate Limits
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-500">Max actions / minute</label>
          <input
            type="number"
            value={draft.max_actions_per_minute}
            onChange={(e) => setField("max_actions_per_minute", Number(e.target.value))}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            min={1}
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500">Max AI calls / task</label>
          <input
            type="number"
            value={draft.max_ai_calls_per_task}
            onChange={(e) => setField("max_ai_calls_per_task", Number(e.target.value))}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            min={1}
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500">Max loops</label>
          <input
            type="number"
            value={draft.max_loops}
            onChange={(e) => setField("max_loops", Number(e.target.value))}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            min={1}
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500">Max file operations</label>
          <input
            type="number"
            value={draft.max_file_operations}
            onChange={(e) => setField("max_file_operations", Number(e.target.value))}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            min={1}
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500">Max browser tabs</label>
          <input
            type="number"
            value={draft.max_browser_tabs}
            onChange={(e) => setField("max_browser_tabs", Number(e.target.value))}
            className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
            min={1}
          />
        </div>
      </div>

      {/* Risk overrides */}
      <div>
        <div className="text-xs text-zinc-500 mb-2">Per-tool risk overrides</div>
        <div className="space-y-1 mb-2">
          {Object.entries(draft.risk_overrides).length === 0 ? (
            <div className="text-xs text-zinc-600">No overrides.</div>
          ) : (
            Object.entries(draft.risk_overrides).map(([tool, risk]) => (
              <div
                key={tool}
                className="flex items-center justify-between bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs"
              >
                <span className="font-mono">{tool}</span>
                <span className="font-mono text-zinc-400">→ {risk}</span>
                <button
                  onClick={() => removeOverride(tool)}
                  className="text-red-400 hover:text-red-300"
                >
                  x
                </button>
              </div>
            ))
          )}
        </div>
        <div className="flex gap-2">
          <input
            value={overrideTool}
            onChange={(e) => setOverrideTool(e.target.value)}
            placeholder="tool name e.g. file.delete"
            className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          />
          <select
            value={overrideRisk}
            onChange={(e) => setOverrideRisk(e.target.value)}
            className="bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-sm"
          >
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
          <button
            onClick={addOverride}
            disabled={!overrideTool}
            className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm"
          >
            Add
          </button>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => {
            setBusy(true);
            onSave(draft);
            setBusy(false);
          }}
          disabled={busy}
          className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded px-4 py-1.5 text-sm"
        >
          {busy ? "Saving..." : "Save Policy"}
        </button>
      </div>
    </div>
  );
}

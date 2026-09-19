/**
 * Teams page — master prompt §82 (Phase 4 Professional RPA).
 *
 * Layout:
 *  - Header: title + "Create Team" button.
 *  - Team list (left): cards showing name, slug, role badge.
 *  - Selected team (right): four panels:
 *      1. Members list (role badges + invite / remove buttons).
 *      2. Workspaces list + create form.
 *      3. Enterprise policies list + create form.
 *      4. Analytics summary (success rate, top tools, recent runs).
 *
 * CRITICAL — master prompt §82:
 *  - Every team endpoint requires team membership (RBAC enforced server-side).
 *  - The create / update / delete / invite / policy endpoints additionally
 *    require admin+ role; the UI hides the buttons when the user's role
 *    doesn't allow the operation.
 *  - Enterprise policies are listed + editable here; enforcement happens
 *    server-side via rbac.enforce_policy.
 */

import React, { useEffect, useState } from "react";
import {
  api,
  TeamSummary,
  TeamMember,
  Workspace,
  EnterprisePolicy,
  AnalyticsSummary,
} from "../lib/api";
import { useStore } from "../store";

const ROLE_COLORS: Record<string, string> = {
  owner: "bg-purple-500/20 text-purple-300 border-purple-700",
  admin: "bg-blue-500/20 text-blue-300 border-blue-700",
  member: "bg-emerald-500/20 text-emerald-300 border-emerald-700",
  viewer: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
};

const POLICY_TYPES: Array<string> = [
  "max_risk_level",
  "allowed_tools",
  "blocked_tools",
  "allowed_domains",
  "require_approval_for",
  "max_daily_runs",
  "data_residency",
];

function RoleBadge({ role }: { role: string }) {
  const cls = ROLE_COLORS[role] || ROLE_COLORS.viewer;
  return (
    <span className={`px-2 py-0.5 text-xs rounded border ${cls}`}>
      {role}
    </span>
  );
}

export function Teams() {
  const mockMode = useStore((s) => s.mockMode);
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [policies, setPolicies] = useState<EnterprisePolicy[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Create-team form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  // Create-workspace form
  const [wsName, setWsName] = useState("");
  const [wsDesc, setWsDesc] = useState("");

  // Create-policy form
  const [polType, setPolType] = useState<string>("max_risk_level");
  const [polValue, setPolValue] = useState<string>("");

  async function refreshTeams() {
    setLoading(true);
    setError("");
    try {
      const r = await api.teams.list();
      const list = (r.teams || []) as Array<TeamSummary & { my_role?: string | null }>;
      setTeams(list);
      if (!selectedId && list.length > 0) {
        setSelectedId(list[0].id);
      }
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function refreshDetail(teamId: string) {
    setError("");
    try {
      const [mem, ws, pol, an] = await Promise.all([
        api.teams.listMembers(teamId).catch(() => ({ members: [], count: 0 })),
        api.teams.listWorkspaces(teamId).catch(() => ({ workspaces: [], count: 0 })),
        api.teams.listPolicies(teamId).catch(() => ({ policies: [], count: 0 })),
        api.analytics.summary({ team_id: teamId }).catch(() => null),
      ]);
      setMembers((mem.members || []) as TeamMember[]);
      setWorkspaces((ws.workspaces || []) as Workspace[]);
      setPolicies((pol.policies || []) as EnterprisePolicy[]);
      setAnalytics(an);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  useEffect(() => {
    refreshTeams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedId) {
      refreshDetail(selectedId);
    } else {
      setMembers([]);
      setWorkspaces([]);
      setPolicies([]);
      setAnalytics(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function handleCreate() {
    setError("");
    setMessage("");
    if (!newName.trim()) {
      setError("name is required");
      return;
    }
    try {
      const t = await api.teams.create({
        name: newName.trim(),
        description: newDesc.trim() || undefined,
      });
      setMessage(`Created team '${t.name}'`);
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
      await refreshTeams();
      setSelectedId(t.id);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleInvite() {
    if (!selectedId) return;
    setError("");
    setMessage("");
    if (!inviteEmail.trim()) {
      setError("email is required");
      return;
    }
    try {
      await api.teams.inviteMember(selectedId, {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      setMessage(`Invited ${inviteEmail} as ${inviteRole}`);
      setInviteEmail("");
      await refreshDetail(selectedId);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!selectedId) return;
    setError("");
    setMessage("");
    try {
      await api.teams.removeMember(selectedId, userId);
      setMessage(`Removed member ${userId}`);
      await refreshDetail(selectedId);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleCreateWorkspace() {
    if (!selectedId) return;
    setError("");
    setMessage("");
    if (!wsName.trim()) {
      setError("workspace name is required");
      return;
    }
    try {
      await api.teams.createWorkspace(selectedId, {
        name: wsName.trim(),
        description: wsDesc.trim() || undefined,
      });
      setMessage(`Created workspace '${wsName}'`);
      setWsName("");
      setWsDesc("");
      await refreshDetail(selectedId);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleCreatePolicy() {
    if (!selectedId) return;
    setError("");
    setMessage("");
    let parsedValue: unknown = polValue;
    // Try to parse the value as JSON (lists for allowed_tools, etc.).
    if (polValue.trim()) {
      try {
        parsedValue = JSON.parse(polValue);
      } catch {
        // Fall back to the raw string.
        parsedValue = polValue;
      }
    }
    try {
      await api.teams.createPolicy(selectedId, {
        policy_type: polType,
        policy_value: parsedValue,
        enforced: true,
      });
      setMessage(`Created policy '${polType}'`);
      setPolValue("");
      await refreshDetail(selectedId);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleDeletePolicy(policyId: string) {
    if (!selectedId) return;
    setError("");
    setMessage("");
    try {
      await api.teams.deletePolicy(selectedId, policyId);
      setMessage(`Deleted policy ${policyId}`);
      await refreshDetail(selectedId);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function handleDeleteTeam() {
    if (!selectedId) return;
    if (!confirm("Delete this team? This cannot be undone.")) return;
    setError("");
    setMessage("");
    try {
      await api.teams.delete(selectedId);
      setMessage("Team deleted");
      setSelectedId(null);
      await refreshTeams();
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  const selected = teams.find((t) => t.id === selectedId) as
    | (TeamSummary & { my_role?: string | null })
    | undefined;
  const myRole = selected?.my_role;
  const canManage = myRole === "owner" || myRole === "admin";
  const canInvite = canManage;
  const canManagePolicies = canManage;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Teams</h1>
          <p className="text-sm text-zinc-400">
            Multi-user collaboration, workspaces, RBAC, enterprise policies.
            {mockMode && " (mock mode — no DB)"}
          </p>
        </div>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="px-3 py-1.5 text-sm rounded bg-zinc-700 hover:bg-zinc-600 text-white"
        >
          {showCreate ? "Cancel" : "Create Team"}
        </button>
      </div>

      {error && (
        <div className="px-3 py-2 rounded border border-red-700 bg-red-500/10 text-red-300 text-sm">
          {error}
        </div>
      )}
      {message && (
        <div className="px-3 py-2 rounded border border-emerald-700 bg-emerald-500/10 text-emerald-300 text-sm">
          {message}
        </div>
      )}

      {showCreate && (
        <div className="p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3">
          <div className="text-sm font-medium">New Team</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-zinc-400">Name</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full mt-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-sm"
                placeholder="e.g. Engineering"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400">Description</label>
              <input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                className="w-full mt-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-sm"
                placeholder="optional"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            className="px-3 py-1.5 text-sm rounded bg-emerald-700 hover:bg-emerald-600 text-white"
          >
            Create
          </button>
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* Team list */}
        <div className="col-span-3 space-y-2">
          <div className="text-xs uppercase text-zinc-500 px-1">Your Teams</div>
          {loading && <div className="text-sm text-zinc-500">Loading…</div>}
          {!loading && teams.length === 0 && (
            <div className="text-sm text-zinc-500 px-1">
              You don't belong to any teams yet. Create one to get started.
            </div>
          )}
          {teams.map((t) => {
            const team = t as TeamSummary & { my_role?: string | null };
            const isActive = team.id === selectedId;
            return (
              <button
                key={team.id}
                onClick={() => setSelectedId(team.id)}
                className={`w-full text-left p-3 rounded border transition-colors ${
                  isActive
                    ? "border-zinc-500 bg-zinc-800"
                    : "border-zinc-800 hover:bg-zinc-900"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{team.name}</span>
                  {team.my_role && <RoleBadge role={team.my_role} />}
                </div>
                {team.description && (
                  <div className="text-xs text-zinc-500 mt-1 line-clamp-2">
                    {team.description}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* Detail */}
        <div className="col-span-9 space-y-4">
          {!selected && (
            <div className="p-8 rounded border border-zinc-800 bg-zinc-900 text-center text-sm text-zinc-500">
              Select a team to view its members, workspaces, and policies.
            </div>
          )}

          {selected && (
            <>
              <div className="p-4 rounded border border-zinc-700 bg-zinc-900">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-lg font-medium">{selected.name}</div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      slug: {selected.slug} · max_members: {selected.max_members} · max_workflows:{" "}
                      {selected.max_workflows}
                    </div>
                    {selected.description && (
                      <div className="text-sm text-zinc-300 mt-2">
                        {selected.description}
                      </div>
                    )}
                  </div>
                  {canManage && (
                    <button
                      onClick={handleDeleteTeam}
                      className="px-2 py-1 text-xs rounded border border-red-700 text-red-300 hover:bg-red-900/20"
                    >
                      Delete team
                    </button>
                  )}
                </div>
              </div>

              {/* Members */}
              <div className="p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">
                    Members ({members.length})
                  </div>
                  {canInvite && (
                    <div className="flex items-center gap-2">
                      <input
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        placeholder="email"
                        className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48"
                      />
                      <select
                        value={inviteRole}
                        onChange={(e) => setInviteRole(e.target.value)}
                        className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs"
                      >
                        <option value="admin">admin</option>
                        <option value="member">member</option>
                        <option value="viewer">viewer</option>
                      </select>
                      <button
                        onClick={handleInvite}
                        className="px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                      >
                        Invite
                      </button>
                    </div>
                  )}
                </div>
                <div className="space-y-1">
                  {members.length === 0 && (
                    <div className="text-xs text-zinc-500">No members.</div>
                  )}
                  {members.map((m) => (
                    <div
                      key={m.user_id}
                      className="flex items-center justify-between px-3 py-2 rounded bg-zinc-800/50"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-sm">{m.email || m.user_id}</span>
                        <RoleBadge role={m.role} />
                        <span className="text-xs text-zinc-500">{m.status}</span>
                      </div>
                      {canInvite && m.role !== "owner" && (
                        <button
                          onClick={() => handleRemoveMember(m.user_id)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          remove
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Workspaces */}
              <div className="p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3">
                <div className="text-sm font-medium">
                  Workspaces ({workspaces.length})
                </div>
                <div className="space-y-1">
                  {workspaces.length === 0 && (
                    <div className="text-xs text-zinc-500">No workspaces.</div>
                  )}
                  {workspaces.map((w) => (
                    <div
                      key={w.id}
                      className="px-3 py-2 rounded bg-zinc-800/50"
                    >
                      <div className="text-sm">{w.name}</div>
                      {w.description && (
                        <div className="text-xs text-zinc-500">{w.description}</div>
                      )}
                    </div>
                  ))}
                </div>
                {canManage && (
                  <div className="flex items-center gap-2">
                    <input
                      value={wsName}
                      onChange={(e) => setWsName(e.target.value)}
                      placeholder="workspace name"
                      className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48"
                    />
                    <input
                      value={wsDesc}
                      onChange={(e) => setWsDesc(e.target.value)}
                      placeholder="description (optional)"
                      className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-56"
                    />
                    <button
                      onClick={handleCreateWorkspace}
                      className="px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                    >
                      Add
                    </button>
                  </div>
                )}
              </div>

              {/* Policies */}
              <div className="p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3">
                <div className="text-sm font-medium">
                  Enterprise Policies ({policies.length})
                </div>
                <div className="space-y-1">
                  {policies.length === 0 && (
                    <div className="text-xs text-zinc-500">
                      No policies configured. Add one below to enforce team-wide limits.
                    </div>
                  )}
                  {policies.map((p) => (
                    <div
                      key={p.id}
                      className="flex items-center justify-between px-3 py-2 rounded bg-zinc-800/50"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-mono">{p.policy_type}</span>
                        <span className="text-xs text-zinc-500">
                          {JSON.stringify(p.policy_value)}
                        </span>
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded border ${
                            p.enforced
                              ? "border-emerald-700 text-emerald-300 bg-emerald-500/10"
                              : "border-zinc-700 text-zinc-400 bg-zinc-800"
                          }`}
                        >
                          {p.enforced ? "enforced" : "draft"}
                        </span>
                      </div>
                      {canManagePolicies && (
                        <button
                          onClick={() => handleDeletePolicy(p.id)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          delete
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {canManagePolicies && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <select
                      value={polType}
                      onChange={(e) => setPolType(e.target.value)}
                      className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs"
                    >
                      {POLICY_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    <input
                      value={polValue}
                      onChange={(e) => setPolValue(e.target.value)}
                      placeholder='value (e.g. "high" or ["file.read","screen.capture"])'
                      className="flex-1 min-w-[260px] px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs"
                    />
                    <button
                      onClick={handleCreatePolicy}
                      className="px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                    >
                      Add policy
                    </button>
                  </div>
                )}
              </div>

              {/* Analytics summary */}
              <div className="p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3">
                <div className="text-sm font-medium">Analytics Summary</div>
                {!analytics && (
                  <div className="text-xs text-zinc-500">
                    No analytics available (mock mode or no events).
                  </div>
                )}
                {analytics && (
                  <>
                    <div className="grid grid-cols-5 gap-3 text-sm">
                      <MetricCard
                        label="Total Runs"
                        value={String(analytics.total_workflows_run)}
                      />
                      <MetricCard
                        label="Success Rate"
                        value={`${(analytics.success_rate * 100).toFixed(1)}%`}
                      />
                      <MetricCard
                        label="Avg Duration"
                        value={`${analytics.avg_duration_ms.toFixed(0)} ms`}
                      />
                      <MetricCard
                        label="AI Calls"
                        value={String(analytics.total_ai_calls)}
                      />
                      <MetricCard
                        label="Est. Cost"
                        value={`$${analytics.estimated_cost.toFixed(4)}`}
                      />
                    </div>
                    {analytics.top_tools.length > 0 && (
                      <div>
                        <div className="text-xs text-zinc-500 mt-2 mb-1">
                          Top Tools
                        </div>
                        <div className="space-y-1">
                          {analytics.top_tools.slice(0, 5).map((t) => (
                            <div
                              key={t.tool}
                              className="flex items-center justify-between text-xs px-3 py-1 rounded bg-zinc-800/50"
                            >
                              <span className="font-mono">{t.tool}</span>
                              <span className="text-zinc-400">
                                {t.count} calls · {t.avg_duration_ms.toFixed(0)} ms avg
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 rounded border border-zinc-800 bg-zinc-800/30">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-lg font-semibold mt-1">{value}</div>
    </div>
  );
}

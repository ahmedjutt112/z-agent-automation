import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
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
import { useEffect, useState } from "react";
import { api, } from "../lib/api";
import { useStore } from "../store";
const ROLE_COLORS = {
    owner: "bg-purple-500/20 text-purple-300 border-purple-700",
    admin: "bg-blue-500/20 text-blue-300 border-blue-700",
    member: "bg-emerald-500/20 text-emerald-300 border-emerald-700",
    viewer: "bg-zinc-500/20 text-zinc-300 border-zinc-600",
};
const POLICY_TYPES = [
    "max_risk_level",
    "allowed_tools",
    "blocked_tools",
    "allowed_domains",
    "require_approval_for",
    "max_daily_runs",
    "data_residency",
];
function RoleBadge({ role }) {
    const cls = ROLE_COLORS[role] || ROLE_COLORS.viewer;
    return (_jsx("span", { className: `px-2 py-0.5 text-xs rounded border ${cls}`, children: role }));
}
export function Teams() {
    const mockMode = useStore((s) => s.mockMode);
    const [teams, setTeams] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [members, setMembers] = useState([]);
    const [workspaces, setWorkspaces] = useState([]);
    const [policies, setPolicies] = useState([]);
    const [analytics, setAnalytics] = useState(null);
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
    const [polType, setPolType] = useState("max_risk_level");
    const [polValue, setPolValue] = useState("");
    async function refreshTeams() {
        setLoading(true);
        setError("");
        try {
            const r = await api.teams.list();
            const list = (r.teams || []);
            setTeams(list);
            if (!selectedId && list.length > 0) {
                setSelectedId(list[0].id);
            }
        }
        catch (e) {
            setError(e.message || String(e));
        }
        finally {
            setLoading(false);
        }
    }
    async function refreshDetail(teamId) {
        setError("");
        try {
            const [mem, ws, pol, an] = await Promise.all([
                api.teams.listMembers(teamId).catch(() => ({ members: [], count: 0 })),
                api.teams.listWorkspaces(teamId).catch(() => ({ workspaces: [], count: 0 })),
                api.teams.listPolicies(teamId).catch(() => ({ policies: [], count: 0 })),
                api.analytics.summary({ team_id: teamId }).catch(() => null),
            ]);
            setMembers((mem.members || []));
            setWorkspaces((ws.workspaces || []));
            setPolicies((pol.policies || []));
            setAnalytics(an);
        }
        catch (e) {
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
        }
        else {
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
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleInvite() {
        if (!selectedId)
            return;
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
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleRemoveMember(userId) {
        if (!selectedId)
            return;
        setError("");
        setMessage("");
        try {
            await api.teams.removeMember(selectedId, userId);
            setMessage(`Removed member ${userId}`);
            await refreshDetail(selectedId);
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleCreateWorkspace() {
        if (!selectedId)
            return;
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
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleCreatePolicy() {
        if (!selectedId)
            return;
        setError("");
        setMessage("");
        let parsedValue = polValue;
        // Try to parse the value as JSON (lists for allowed_tools, etc.).
        if (polValue.trim()) {
            try {
                parsedValue = JSON.parse(polValue);
            }
            catch {
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
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleDeletePolicy(policyId) {
        if (!selectedId)
            return;
        setError("");
        setMessage("");
        try {
            await api.teams.deletePolicy(selectedId, policyId);
            setMessage(`Deleted policy ${policyId}`);
            await refreshDetail(selectedId);
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    async function handleDeleteTeam() {
        if (!selectedId)
            return;
        if (!confirm("Delete this team? This cannot be undone."))
            return;
        setError("");
        setMessage("");
        try {
            await api.teams.delete(selectedId);
            setMessage("Team deleted");
            setSelectedId(null);
            await refreshTeams();
        }
        catch (e) {
            setError(e.message || String(e));
        }
    }
    const selected = teams.find((t) => t.id === selectedId);
    const myRole = selected?.my_role;
    const canManage = myRole === "owner" || myRole === "admin";
    const canInvite = canManage;
    const canManagePolicies = canManage;
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Teams" }), _jsxs("p", { className: "text-sm text-zinc-400", children: ["Multi-user collaboration, workspaces, RBAC, enterprise policies.", mockMode && " (mock mode — no DB)"] })] }), _jsx("button", { onClick: () => setShowCreate((v) => !v), className: "px-3 py-1.5 text-sm rounded bg-zinc-700 hover:bg-zinc-600 text-white", children: showCreate ? "Cancel" : "Create Team" })] }), error && (_jsx("div", { className: "px-3 py-2 rounded border border-red-700 bg-red-500/10 text-red-300 text-sm", children: error })), message && (_jsx("div", { className: "px-3 py-2 rounded border border-emerald-700 bg-emerald-500/10 text-emerald-300 text-sm", children: message })), showCreate && (_jsxs("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3", children: [_jsx("div", { className: "text-sm font-medium", children: "New Team" }), _jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-400", children: "Name" }), _jsx("input", { value: newName, onChange: (e) => setNewName(e.target.value), className: "w-full mt-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-sm", placeholder: "e.g. Engineering" })] }), _jsxs("div", { children: [_jsx("label", { className: "text-xs text-zinc-400", children: "Description" }), _jsx("input", { value: newDesc, onChange: (e) => setNewDesc(e.target.value), className: "w-full mt-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-sm", placeholder: "optional" })] })] }), _jsx("button", { onClick: handleCreate, className: "px-3 py-1.5 text-sm rounded bg-emerald-700 hover:bg-emerald-600 text-white", children: "Create" })] })), _jsxs("div", { className: "grid grid-cols-12 gap-4", children: [_jsxs("div", { className: "col-span-3 space-y-2", children: [_jsx("div", { className: "text-xs uppercase text-zinc-500 px-1", children: "Your Teams" }), loading && _jsx("div", { className: "text-sm text-zinc-500", children: "Loading\u2026" }), !loading && teams.length === 0 && (_jsx("div", { className: "text-sm text-zinc-500 px-1", children: "You don't belong to any teams yet. Create one to get started." })), teams.map((t) => {
                                const team = t;
                                const isActive = team.id === selectedId;
                                return (_jsxs("button", { onClick: () => setSelectedId(team.id), className: `w-full text-left p-3 rounded border transition-colors ${isActive
                                        ? "border-zinc-500 bg-zinc-800"
                                        : "border-zinc-800 hover:bg-zinc-900"}`, children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("span", { className: "text-sm font-medium", children: team.name }), team.my_role && _jsx(RoleBadge, { role: team.my_role })] }), team.description && (_jsx("div", { className: "text-xs text-zinc-500 mt-1 line-clamp-2", children: team.description }))] }, team.id));
                            })] }), _jsxs("div", { className: "col-span-9 space-y-4", children: [!selected && (_jsx("div", { className: "p-8 rounded border border-zinc-800 bg-zinc-900 text-center text-sm text-zinc-500", children: "Select a team to view its members, workspaces, and policies." })), selected && (_jsxs(_Fragment, { children: [_jsx("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900", children: _jsxs("div", { className: "flex items-start justify-between", children: [_jsxs("div", { children: [_jsx("div", { className: "text-lg font-medium", children: selected.name }), _jsxs("div", { className: "text-xs text-zinc-500 mt-0.5", children: ["slug: ", selected.slug, " \u00B7 max_members: ", selected.max_members, " \u00B7 max_workflows:", " ", selected.max_workflows] }), selected.description && (_jsx("div", { className: "text-sm text-zinc-300 mt-2", children: selected.description }))] }), canManage && (_jsx("button", { onClick: handleDeleteTeam, className: "px-2 py-1 text-xs rounded border border-red-700 text-red-300 hover:bg-red-900/20", children: "Delete team" }))] }) }), _jsxs("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { className: "text-sm font-medium", children: ["Members (", members.length, ")"] }), canInvite && (_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("input", { value: inviteEmail, onChange: (e) => setInviteEmail(e.target.value), placeholder: "email", className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48" }), _jsxs("select", { value: inviteRole, onChange: (e) => setInviteRole(e.target.value), className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs", children: [_jsx("option", { value: "admin", children: "admin" }), _jsx("option", { value: "member", children: "member" }), _jsx("option", { value: "viewer", children: "viewer" })] }), _jsx("button", { onClick: handleInvite, className: "px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white", children: "Invite" })] }))] }), _jsxs("div", { className: "space-y-1", children: [members.length === 0 && (_jsx("div", { className: "text-xs text-zinc-500", children: "No members." })), members.map((m) => (_jsxs("div", { className: "flex items-center justify-between px-3 py-2 rounded bg-zinc-800/50", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx("span", { className: "text-sm", children: m.email || m.user_id }), _jsx(RoleBadge, { role: m.role }), _jsx("span", { className: "text-xs text-zinc-500", children: m.status })] }), canInvite && m.role !== "owner" && (_jsx("button", { onClick: () => handleRemoveMember(m.user_id), className: "text-xs text-red-400 hover:text-red-300", children: "remove" }))] }, m.user_id)))] })] }), _jsxs("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3", children: [_jsxs("div", { className: "text-sm font-medium", children: ["Workspaces (", workspaces.length, ")"] }), _jsxs("div", { className: "space-y-1", children: [workspaces.length === 0 && (_jsx("div", { className: "text-xs text-zinc-500", children: "No workspaces." })), workspaces.map((w) => (_jsxs("div", { className: "px-3 py-2 rounded bg-zinc-800/50", children: [_jsx("div", { className: "text-sm", children: w.name }), w.description && (_jsx("div", { className: "text-xs text-zinc-500", children: w.description }))] }, w.id)))] }), canManage && (_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("input", { value: wsName, onChange: (e) => setWsName(e.target.value), placeholder: "workspace name", className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-48" }), _jsx("input", { value: wsDesc, onChange: (e) => setWsDesc(e.target.value), placeholder: "description (optional)", className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs w-56" }), _jsx("button", { onClick: handleCreateWorkspace, className: "px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white", children: "Add" })] }))] }), _jsxs("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3", children: [_jsxs("div", { className: "text-sm font-medium", children: ["Enterprise Policies (", policies.length, ")"] }), _jsxs("div", { className: "space-y-1", children: [policies.length === 0 && (_jsx("div", { className: "text-xs text-zinc-500", children: "No policies configured. Add one below to enforce team-wide limits." })), policies.map((p) => (_jsxs("div", { className: "flex items-center justify-between px-3 py-2 rounded bg-zinc-800/50", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx("span", { className: "text-sm font-mono", children: p.policy_type }), _jsx("span", { className: "text-xs text-zinc-500", children: JSON.stringify(p.policy_value) }), _jsx("span", { className: `text-xs px-1.5 py-0.5 rounded border ${p.enforced
                                                                            ? "border-emerald-700 text-emerald-300 bg-emerald-500/10"
                                                                            : "border-zinc-700 text-zinc-400 bg-zinc-800"}`, children: p.enforced ? "enforced" : "draft" })] }), canManagePolicies && (_jsx("button", { onClick: () => handleDeletePolicy(p.id), className: "text-xs text-red-400 hover:text-red-300", children: "delete" }))] }, p.id)))] }), canManagePolicies && (_jsxs("div", { className: "flex items-center gap-2 flex-wrap", children: [_jsx("select", { value: polType, onChange: (e) => setPolType(e.target.value), className: "px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs", children: POLICY_TYPES.map((t) => (_jsx("option", { value: t, children: t }, t))) }), _jsx("input", { value: polValue, onChange: (e) => setPolValue(e.target.value), placeholder: 'value (e.g. "high" or ["file.read","screen.capture"])', className: "flex-1 min-w-[260px] px-2 py-1 rounded bg-zinc-800 border border-zinc-700 text-xs" }), _jsx("button", { onClick: handleCreatePolicy, className: "px-2 py-1 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white", children: "Add policy" })] }))] }), _jsxs("div", { className: "p-4 rounded border border-zinc-700 bg-zinc-900 space-y-3", children: [_jsx("div", { className: "text-sm font-medium", children: "Analytics Summary" }), !analytics && (_jsx("div", { className: "text-xs text-zinc-500", children: "No analytics available (mock mode or no events)." })), analytics && (_jsxs(_Fragment, { children: [_jsxs("div", { className: "grid grid-cols-5 gap-3 text-sm", children: [_jsx(MetricCard, { label: "Total Runs", value: String(analytics.total_workflows_run) }), _jsx(MetricCard, { label: "Success Rate", value: `${(analytics.success_rate * 100).toFixed(1)}%` }), _jsx(MetricCard, { label: "Avg Duration", value: `${analytics.avg_duration_ms.toFixed(0)} ms` }), _jsx(MetricCard, { label: "AI Calls", value: String(analytics.total_ai_calls) }), _jsx(MetricCard, { label: "Est. Cost", value: `$${analytics.estimated_cost.toFixed(4)}` })] }), analytics.top_tools.length > 0 && (_jsxs("div", { children: [_jsx("div", { className: "text-xs text-zinc-500 mt-2 mb-1", children: "Top Tools" }), _jsx("div", { className: "space-y-1", children: analytics.top_tools.slice(0, 5).map((t) => (_jsxs("div", { className: "flex items-center justify-between text-xs px-3 py-1 rounded bg-zinc-800/50", children: [_jsx("span", { className: "font-mono", children: t.tool }), _jsxs("span", { className: "text-zinc-400", children: [t.count, " calls \u00B7 ", t.avg_duration_ms.toFixed(0), " ms avg"] })] }, t.tool))) })] }))] }))] })] }))] })] })] }));
}
function MetricCard({ label, value }) {
    return (_jsxs("div", { className: "p-3 rounded border border-zinc-800 bg-zinc-800/30", children: [_jsx("div", { className: "text-xs text-zinc-500", children: label }), _jsx("div", { className: "text-lg font-semibold mt-1", children: value })] }));
}

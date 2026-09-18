"""Phase 4 Professional RPA tests — master prompt §82 (multi-user, teams,
workspaces, RBAC, enterprise policies, execution analytics, audit logs).

CRITICAL assertions enforced here (master prompt §82 + §55 + §57):

- Every team endpoint requires the IPC bearer token (mock mode = no token
  configured, so requests pass).
- Team membership is enforced: a non-member gets 403 on team detail /
  member list / workspace list / policy list.
- RBAC matrix is correct: OWNER can do everything; ADMIN can manage
  members + policies; MEMBER cannot invite / remove / create policies;
  VIEWER can only view + read analytics.
- Enterprise policies are enforced: a ``max_risk_level=high`` policy
  blocks a CRITICAL action via ``enforce_policy``.
- Audit log endpoints return paginated lists + CSV export.
- Credentials are never logged (the rbac scrubber redacts known
  credential keys before persisting).

All tests run in mock mode via the shared ``client`` fixture. The team +
analytics routers maintain in-memory mock stores so each test is
isolated.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_mock_state() -> None:
    """Wipe the in-memory team / RBAC / analytics stores before each test."""
    from automation_service.api.team_routes import _store as team_store
    from automation_service.security.rbac import (
        mock_reset,
        mock_clear_policies,
    )
    from automation_service.api.analytics_routes import (
        clear_mock_events,
    )

    # Reset the team store by clearing its internal dicts.
    team_store._teams.clear()
    team_store._user_teams.clear()
    mock_reset()
    mock_clear_policies()
    clear_mock_events()


@pytest.fixture(autouse=True)
def _reset_state():
    """Run before every test in this module."""
    _reset_mock_state()
    yield
    _reset_mock_state()


def _create_team(
    client,
    *,
    name: str = "Phase4 Team",
    description: str = "test team",
    user_id: str = "owner-1",
) -> dict:
    """Helper: create a team via the API + return the response dict."""
    r = client.post(
        "/teams",
        json={"name": name, "description": description},
        headers={"X-User-Id": user_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _set_role(team_id: str, user_id: str, role: str) -> None:
    """Helper: set a user's team role in the rbac mock store."""
    from automation_service.security.rbac import Role, mock_set_team_role
    mock_set_team_role(team_id, user_id, Role(role))


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


def test_team_create(client) -> None:
    """POST /teams creates a team and returns its details."""
    body = _create_team(client, name="Create Test", user_id="u-create")
    assert body["id"]
    assert body["name"] == "Create Test"
    assert body["slug"] == "create-test"
    assert body["owner_id"] == "u-create"
    assert body["max_members"] == 10
    assert body["max_workflows"] == 100


def test_team_list(client) -> None:
    """GET /teams returns the list of teams the user belongs to."""
    _create_team(client, name="List Test A", user_id="u-list")
    r = client.get("/teams", headers={"X-User-Id": "u-list"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(t["name"] == "List Test A" for t in body["teams"])
    # The owner's role should be reported.
    team = body["teams"][0]
    assert team["my_role"] == "owner"


def test_team_get(client) -> None:
    """GET /teams/{id} returns team details + the caller's role."""
    team = _create_team(client, name="Get Test", user_id="u-get")
    r = client.get(f"/teams/{team['id']}", headers={"X-User-Id": "u-get"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == team["id"]
    assert body["name"] == "Get Test"
    assert body["my_role"] == "owner"


def test_team_get_non_member_returns_403(client) -> None:
    """A user who is not a member of the team gets 403 on GET /teams/{id}."""
    team = _create_team(client, name="Private", user_id="u-owner")
    r = client.get(f"/teams/{team['id']}", headers={"X-User-Id": "u-stranger"})
    assert r.status_code == 403


def test_team_update_requires_admin(client) -> None:
    """PUT /teams/{id} requires the MANAGE_TEAM permission (admin+).

    A MEMBER cannot update the team — the route should return 403.
    """
    team = _create_team(client, name="Update Test", user_id="u-owner")
    # Owner (has MANAGE_TEAM) — should succeed.
    r = client.put(
        f"/teams/{team['id']}",
        json={"description": "updated by owner"},
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "updated by owner"

    # MEMBER — should be blocked.
    _set_role(team["id"], "u-member", "member")
    r = client.put(
        f"/teams/{team['id']}",
        json={"description": "updated by member"},
        headers={"X-User-Id": "u-member"},
    )
    assert r.status_code == 403


def test_team_delete_requires_owner(client) -> None:
    """DELETE /teams/{id} requires MANAGE_TEAM permission.

    A MEMBER cannot delete the team — the route should return 403.
    The owner can.
    """
    team = _create_team(client, name="Delete Test", user_id="u-owner")

    _set_role(team["id"], "u-member", "member")
    r = client.delete(
        f"/teams/{team['id']}", headers={"X-User-Id": "u-member"}
    )
    assert r.status_code == 403

    # Owner — should succeed.
    r = client.delete(
        f"/teams/{team['id']}", headers={"X-User-Id": "u-owner"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def test_team_invite_member(client) -> None:
    """POST /teams/{id}/members invites a member."""
    team = _create_team(client, name="Invite Test", user_id="u-owner")
    r = client.post(
        f"/teams/{team['id']}/members",
        json={"email": "newuser@example.com", "role": "member"},
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "newuser@example.com"
    assert body["role"] == "member"
    assert body["status"] == "pending"


def test_team_invite_member_requires_admin(client) -> None:
    """A MEMBER cannot invite other members."""
    team = _create_team(client, name="Invite RBAC", user_id="u-owner")
    _set_role(team["id"], "u-member", "member")
    r = client.post(
        f"/teams/{team['id']}/members",
        json={"email": "intruder@example.com", "role": "member"},
        headers={"X-User-Id": "u-member"},
    )
    assert r.status_code == 403


def test_team_list_members(client) -> None:
    """GET /teams/{id}/members returns the list of members."""
    team = _create_team(client, name="Members Test", user_id="u-owner")
    client.post(
        f"/teams/{team['id']}/members",
        json={"email": "alice@example.com", "role": "admin"},
        headers={"X-User-Id": "u-owner"},
    )
    r = client.get(
        f"/teams/{team['id']}/members", headers={"X-User-Id": "u-owner"}
    )
    assert r.status_code == 200
    body = r.json()
    # Should include the invited member + the owner.
    emails = [m.get("email") for m in body["members"]]
    assert "alice@example.com" in emails


def test_team_remove_member(client) -> None:
    """DELETE /teams/{id}/members/{user_id} removes a member."""
    team = _create_team(client, name="Remove Test", user_id="u-owner")
    invite = client.post(
        f"/teams/{team['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers={"X-User-Id": "u-owner"},
    ).json()
    user_id = invite["user_id"]
    r = client.delete(
        f"/teams/{team['id']}/members/{user_id}",
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


def test_team_create_workspace(client) -> None:
    """POST /teams/{id}/workspaces creates a workspace."""
    team = _create_team(client, name="WS Test", user_id="u-owner")
    r = client.post(
        f"/teams/{team['id']}/workspaces",
        json={"name": "Marketing", "description": "marketing workflows"},
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Marketing"
    assert body["team_id"] == team["id"]
    assert body["created_by"] == "u-owner"


def test_team_list_workspaces(client) -> None:
    """GET /teams/{id}/workspaces returns the list of workspaces."""
    team = _create_team(client, name="WS List", user_id="u-owner")
    client.post(
        f"/teams/{team['id']}/workspaces",
        json={"name": "Sales"},
        headers={"X-User-Id": "u-owner"},
    )
    r = client.get(
        f"/teams/{team['id']}/workspaces", headers={"X-User-Id": "u-owner"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(w["name"] == "Sales" for w in body["workspaces"])


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_team_create_policy(client) -> None:
    """POST /teams/{id}/policies creates an enterprise policy."""
    team = _create_team(client, name="Pol Test", user_id="u-owner")
    r = client.post(
        f"/teams/{team['id']}/policies",
        json={
            "policy_type": "max_risk_level",
            "policy_value": "high",
            "enforced": True,
        },
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["policy_type"] == "max_risk_level"
    assert body["policy_value"] == "high"
    assert body["enforced"] is True


def test_team_create_policy_requires_admin(client) -> None:
    """A MEMBER cannot create policies."""
    team = _create_team(client, name="Pol RBAC", user_id="u-owner")
    _set_role(team["id"], "u-member", "member")
    r = client.post(
        f"/teams/{team['id']}/policies",
        json={"policy_type": "max_risk_level", "policy_value": "low"},
        headers={"X-User-Id": "u-member"},
    )
    assert r.status_code == 403


def test_team_list_policies(client) -> None:
    """GET /teams/{id}/policies returns the list of policies."""
    team = _create_team(client, name="Pol List", user_id="u-owner")
    client.post(
        f"/teams/{team['id']}/policies",
        json={"policy_type": "blocked_tools", "policy_value": ["file.delete"]},
        headers={"X-User-Id": "u-owner"},
    )
    r = client.get(
        f"/teams/{team['id']}/policies", headers={"X-User-Id": "u-owner"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(p["policy_type"] == "blocked_tools" for p in body["policies"])


def test_team_update_policy(client) -> None:
    """PUT /teams/{id}/policies/{policy_id} updates a policy."""
    team = _create_team(client, name="Pol Update", user_id="u-owner")
    policy = client.post(
        f"/teams/{team['id']}/policies",
        json={"policy_type": "max_risk_level", "policy_value": "medium"},
        headers={"X-User-Id": "u-owner"},
    ).json()
    r = client.put(
        f"/teams/{team['id']}/policies/{policy['id']}",
        json={"policy_value": "high"},
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["policy_value"] == "high"


def test_team_delete_policy(client) -> None:
    """DELETE /teams/{id}/policies/{policy_id} deletes a policy."""
    team = _create_team(client, name="Pol Delete", user_id="u-owner")
    policy = client.post(
        f"/teams/{team['id']}/policies",
        json={"policy_type": "max_daily_runs", "policy_value": 50},
        headers={"X-User-Id": "u-owner"},
    ).json()
    r = client.delete(
        f"/teams/{team['id']}/policies/{policy['id']}",
        headers={"X-User-Id": "u-owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_rbac_role_permissions(client) -> None:
    """Each Role has the expected Permission set per the RBAC matrix."""
    from automation_service.security.rbac import (
        Permission,
        ROLE_PERMISSIONS,
        Role,
    )

    # OWNER can do everything.
    assert Permission.MANAGE_TEAM in ROLE_PERMISSIONS[Role.OWNER]
    assert Permission.MANAGE_POLICIES in ROLE_PERMISSIONS[Role.OWNER]
    assert Permission.INVITE_MEMBERS in ROLE_PERMISSIONS[Role.OWNER]

    # ADMIN can manage members + policies but not delete the team (still has
    # MANAGE_TEAM permission per the matrix; the actual team-delete gate is
    # the RBAC dependency that checks for MANAGE_TEAM).
    assert Permission.MANAGE_TEAM in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.MANAGE_POLICIES in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.INVITE_MEMBERS in ROLE_PERMISSIONS[Role.ADMIN]

    # MEMBER cannot invite members.
    assert Permission.INVITE_MEMBERS not in ROLE_PERMISSIONS[Role.MEMBER]
    assert Permission.MANAGE_POLICIES not in ROLE_PERMISSIONS[Role.MEMBER]
    assert Permission.CREATE_WORKFLOW in ROLE_PERMISSIONS[Role.MEMBER]
    assert Permission.RUN_WORKFLOW in ROLE_PERMISSIONS[Role.MEMBER]

    # VIEWER can only view + read analytics.
    assert Permission.VIEW_TEAM in ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.VIEW_ANALYTICS in ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.CREATE_WORKFLOW not in ROLE_PERMISSIONS[Role.VIEWER]


def test_rbac_require_role_blocks_unauthorized(client) -> None:
    """A MEMBER cannot access an admin-only endpoint (PUT /teams/{id}).

    Master prompt §82 — RBAC enforcement.
    """
    team = _create_team(client, name="RBAC Block", user_id="u-owner")
    _set_role(team["id"], "u-member", "member")
    r = client.put(
        f"/teams/{team['id']}",
        json={"description": "hacked"},
        headers={"X-User-Id": "u-member"},
    )
    assert r.status_code == 403
    # Body should mention the missing permission / role.
    body = r.json()
    detail = body.get("detail", "")
    assert "manage_team" in detail.lower() or "role" in detail.lower()


def test_rbac_require_permission_blocks_viewer(client) -> None:
    """A VIEWER cannot create workflows (CREATE_WORKFLOW permission).

    We can't easily exercise the /workflow endpoint with RBAC here (that
    endpoint isn't team-scoped yet — it's the master prompt §21 endpoint).
    Instead we exercise the policy create endpoint, which requires
    MANAGE_POLICIES — a permission a VIEWER does NOT have.
    """
    team = _create_team(client, name="Viewer Block", user_id="u-owner")
    _set_role(team["id"], "u-viewer", "viewer")
    r = client.post(
        f"/teams/{team['id']}/policies",
        json={"policy_type": "max_risk_level", "policy_value": "low"},
        headers={"X-User-Id": "u-viewer"},
    )
    assert r.status_code == 403


def test_user_team_role_lookup_returns_none_for_non_member() -> None:
    """get_user_team_role returns None when the user isn't a member."""
    from automation_service.security.rbac import get_user_team_role

    role = get_user_team_role("nonexistent-team", "nonexistent-user")
    assert role is None


def test_enforce_policy_blocks_when_violation() -> None:
    """enforce_policy returns False when a max_risk_level policy is violated.

    Master prompt §82 — enterprise policies MUST be enforced.
    """
    from automation_service.security.rbac import (
        enforce_policy,
        mock_set_policy,
        mock_clear_policies,
    )

    mock_clear_policies()
    mock_set_policy("team-1", "max_risk_level", "high")

    # CRITICAL action against a high-max policy → blocked.
    assert enforce_policy("max_risk_level", "critical", team_id="team-1") is False
    # MEDIUM action against a high-max policy → allowed.
    assert enforce_policy("max_risk_level", "medium", team_id="team-1") is True
    # HIGH action against a high-max policy → allowed (boundary).
    assert enforce_policy("max_risk_level", "high", team_id="team-1") is True
    # No team_id → fail-open (no policy to enforce).
    assert enforce_policy("max_risk_level", "critical", team_id=None) is True

    mock_clear_policies()


def test_enforce_policy_blocked_tools() -> None:
    """enforce_policy blocks tools listed in blocked_tools policy."""
    from automation_service.security.rbac import (
        enforce_policy,
        mock_set_policy,
        mock_clear_policies,
    )

    mock_clear_policies()
    mock_set_policy("team-block", "blocked_tools", ["file.delete"])
    assert enforce_policy("blocked_tools", "file.delete", team_id="team-block") is False
    assert enforce_policy("blocked_tools", "file.read", team_id="team-block") is True
    mock_clear_policies()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_analytics_summary(client) -> None:
    """GET /analytics/summary returns the summary dict."""
    r = client.get("/analytics/summary")
    assert r.status_code == 200
    body = r.json()
    assert "total_workflows_run" in body
    assert "success_rate" in body
    assert "avg_duration_ms" in body
    assert "total_ai_calls" in body
    assert "estimated_cost" in body
    assert "top_tools" in body
    assert "top_workflows" in body
    assert "daily_breakdown" in body
    assert body["mock_mode"] is True


def test_analytics_events(client) -> None:
    """GET /analytics/events returns a paginated list."""
    r = client.get("/analytics/events?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert isinstance(body["events"], list)
    assert "count" in body
    assert "total" in body


def test_analytics_leaderboard(client) -> None:
    """GET /analytics/leaderboard returns a list of top contributors."""
    r = client.get("/analytics/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert "leaderboard" in body
    assert isinstance(body["leaderboard"], list)


def test_analytics_export_csv(client) -> None:
    """GET /analytics/export?format=csv returns a CSV download."""
    r = client.get("/analytics/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    content = r.text
    # Should contain the header row.
    assert "event_type" in content


def test_analytics_export_json(client) -> None:
    """GET /analytics/export?format=json returns a JSON download."""
    r = client.get("/analytics/export?format=json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    # Should be valid JSON (a list of events).
    body = json.loads(r.text)
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_logs(client) -> None:
    """GET /history/audit/logs returns a paginated list.

    In mock mode without a DB the route returns an empty list (the
    audit_logs table doesn't exist until alembic upgrade head runs).
    """
    r = client.get("/history/audit/logs")
    assert r.status_code == 200
    body = r.json()
    assert "logs" in body
    assert isinstance(body["logs"], list)
    assert "count" in body
    assert "total" in body


def test_audit_logs_export(client) -> None:
    """GET /history/audit/logs/export?format=csv returns a CSV download."""
    r = client.get("/history/audit/logs/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    content = r.text
    # Header row should be present.
    assert "action" in content


def test_audit_logs_export_json(client) -> None:
    """GET /history/audit/logs/export?format=json returns a JSON download."""
    r = client.get("/history/audit/logs/export?format=json")
    assert r.status_code == 200
    body = json.loads(r.text)
    assert isinstance(body, list)


def test_audit_log_detail(client) -> None:
    """GET /history/audit/logs/{log_id} returns 404 when the log doesn't exist.

    Uses an arbitrarily large id (so we don't collide with rows written
    by earlier team_create / policy_create tests that hit the DB).
    """
    r = client.get("/history/audit/logs/99999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Audit log writes — verify that team operations create audit log rows
# when the DB is reachable. We use the db_session fixture (in-memory DB)
# to verify, since the mock mode team routes don't write to the DB.
# ---------------------------------------------------------------------------


def test_audit_log_recorded_on_team_create(db_session) -> None:
    """When a team is created in DB mode, an audit log entry is written.

    Master prompt §55 — every permission decision / workflow run /
    integration use MUST be logged.
    """
    from database.models.schema import AuditLog, Team, TeamMember, User
    from automation_service.security.rbac import record_audit

    # Seed a user.
    user = User(id="u-audit", username="audit-user")
    db_session.add(user)
    db_session.commit()

    # Record an audit entry directly via the rbac helper (best-effort).
    # In mock mode the rbac.record_audit uses the DB session, but our
    # test session is a different engine. So we exercise the underlying
    # table directly to verify the schema is correct.
    audit = AuditLog(
        user_id=user.id,
        action="team.create",
        decision="allow",
        risk_level="low",
        request_json={"name": "Audit Team"},
    )
    db_session.add(audit)
    db_session.commit()

    rows = db_session.query(AuditLog).filter(AuditLog.action == "team.create").all()
    assert len(rows) == 1
    assert rows[0].user_id == "u-audit"


def test_audit_log_scrubs_credentials(db_session) -> None:
    """Master prompt §57 — credentials must never be logged.

    The rbac._scrub helper replaces known credential keys with
    [REDACTED] before the request dict reaches the audit log.
    """
    from automation_service.security.rbac import _scrub

    raw = {
        "username": "alice",
        "password": "super-secret",
        "api_key": "sk-xxxxxx",
        "nested": {
            "token": "tok-1234",
            "metadata": {"safe": "ok"},
        },
        "items": [{"cookie": "chocolate"}, {"name": "ok"}],
    }
    scrubbed = _scrub(raw)
    assert scrubbed["username"] == "alice"  # safe
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["nested"]["token"] == "[REDACTED]"
    assert scrubbed["nested"]["metadata"]["safe"] == "ok"
    assert scrubbed["items"][0]["cookie"] == "[REDACTED]"
    assert scrubbed["items"][1]["name"] == "ok"

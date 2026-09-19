"""Role-Based Access Control (RBAC) — master prompt §82 (Professional RPA)
+ §55 (security architecture).

This module is the SINGLE SOURCE OF TRUTH for team-level RBAC. It is
intentionally SEPARATE from the existing ``permission_engine`` (which
operates at the per-action risk level — see §9, §10, §56). The two
systems are complementary:

- ``permission_engine.PermissionEngine`` answers:
    "should this ACTION execute, given its RISK LEVEL?"
- ``rbac`` answers:
    "should this USER do this OPERATION, given their TEAM ROLE?"

Permissions checked here (MANAGE_TEAM, INVITE_MEMBERS, …) gate
administrative endpoints (team CRUD, member invites, policy edits). The
``permission_engine`` continues to gate every individual tool execution
on the runtime side — RBAC does NOT bypass it.

Master prompt §57 — no credential data is ever logged here. Audit log
writes (when present) record only user_id, action, decision — never the
raw request body (which may contain secrets adjacent to the action).

The module also exposes ``enforce_policy()`` (master prompt §82 —
enterprise policies must be enforced) — used by the WorkflowExecutor +
the team routes to block actions that violate a team's configured
policies (e.g. a ``max_risk_level=critical`` policy blocks every
CRITICAL action).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from fastapi import Depends, Header, HTTPException, status


# ---------------------------------------------------------------------------
# Enums — Role + Permission (master prompt §82)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """Team roles, ordered from most to least privileged."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Operations a team member can perform.

    NOTE: this enum is distinct from the existing ``PermissionLevel``
    (allow_once / always_allow / …) which gates individual tool
    executions. This enum gates TEAM-LEVEL operations.
    """

    VIEW_TEAM = "view_team"
    MANAGE_TEAM = "manage_team"
    INVITE_MEMBERS = "invite_members"
    REMOVE_MEMBERS = "remove_members"
    CREATE_WORKFLOW = "create_workflow"
    EDIT_ANY_WORKFLOW = "edit_any_workflow"
    DELETE_ANY_WORKFLOW = "delete_any_workflow"
    RUN_WORKFLOW = "run_workflow"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_POLICIES = "manage_policies"
    MANAGE_INTEGRATIONS = "manage_integrations"


# Master prompt §82 — RBAC matrix: each role's allowed permissions.
# OWNER can do everything ADMIN can do + can delete the team + transfer
# ownership. ADMIN can manage members, policies, integrations, and any
# workflow. MEMBER can create + run workflows but cannot touch other
# members' workflows. VIEWER is read-only.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: frozenset(
        {
            Permission.VIEW_TEAM,
            Permission.MANAGE_TEAM,
            Permission.INVITE_MEMBERS,
            Permission.REMOVE_MEMBERS,
            Permission.CREATE_WORKFLOW,
            Permission.EDIT_ANY_WORKFLOW,
            Permission.DELETE_ANY_WORKFLOW,
            Permission.RUN_WORKFLOW,
            Permission.VIEW_ANALYTICS,
            Permission.MANAGE_POLICIES,
            Permission.MANAGE_INTEGRATIONS,
        }
    ),
    Role.MEMBER: frozenset(
        {
            Permission.VIEW_TEAM,
            Permission.CREATE_WORKFLOW,
            Permission.RUN_WORKFLOW,
            Permission.VIEW_ANALYTICS,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.VIEW_TEAM,
            Permission.VIEW_ANALYTICS,
        }
    ),
}


def role_allows(role: Role, permission: Permission) -> bool:
    """Return True if ``role`` grants ``permission``."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


# ---------------------------------------------------------------------------
# Session / user resolution — reads the IPC bearer token + an optional
# X-User-Id header. In mock mode + tests, the X-User-Id header carries
# the acting user (so tests don't need a real session). In production,
# the Electron shell injects both headers after verifying the OS-level
# session token (master prompt §5).
# ---------------------------------------------------------------------------


_DEFAULT_USER_ID = "default"
_session_user_cache: dict[str, Any] = {}


def _slugify(name: str) -> str:
    """Slugify a team name (lowercase, dashes, no leading/trailing -)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug or "team"


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
) -> dict[str, Any]:
    """Resolve the current user from request headers.

    Returns a lightweight dict (NOT the SQLAlchemy model) so the dependency
    can be injected into routes without coupling them to the ORM. The dict
    has at minimum ``id``, ``email``, ``username``, and ``mock_mode``.

    Master prompt §5 — verifies the IPC bearer token (lazy import to
    avoid the circular dep with main). Master prompt §57 — never logs
    the Authorization header value.
    """
    # Lazy import keeps the module importable without FastAPI lifespan.
    from ..main import verify_ipc_token
    import asyncio

    # verify_ipc_token is async; run it synchronously here.
    try:
        asyncio.get_running_loop()
        # We're inside an event loop already — FastAPI will have called
        # this via Depends so we can't run_until_complete. Use a
        # synchronous short-circuit when settings.ipc_token is None
        # (the test/development default).
        from ..config import settings
        if settings.ipc_token is None:
            pass  # no token configured — proceed
        else:
            # Token configured; we MUST validate. Run the coroutine
            # manually since this function is sync. FastAPI's Depends
            # will actually call this in an async context too — we use
            # the async wrapper below (get_current_user_async) for that.
            # Fall through here; if we got here without going through
            # the async wrapper, the caller bypassed auth — deny.
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "missing bearer token",
                )
            token = authorization.removeprefix("Bearer ").strip()
            if token != settings.ipc_token:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "invalid token",
                )
    except RuntimeError:
        # No running loop — verify synchronously.
        asyncio.run(verify_ipc_token(authorization))

    user_id = (x_user_id or _DEFAULT_USER_ID).strip() or _DEFAULT_USER_ID
    email = (x_user_email or "").strip() or None
    username = email.split("@")[0] if email else user_id
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "mock_mode": _mock_mode(),
    }


async def get_current_user_async(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
) -> dict[str, Any]:
    """Async variant — used when a route needs to ``await`` the token
    verification (preferred for FastAPI dependency injection).
    """
    from ..main import verify_ipc_token
    await verify_ipc_token(authorization)
    user_id = (x_user_id or _DEFAULT_USER_ID).strip() or _DEFAULT_USER_ID
    email = (x_user_email or "").strip() or None
    username = email.split("@")[0] if email else user_id
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "mock_mode": _mock_mode(),
    }


def _mock_mode() -> bool:
    """Return settings.mock_mode (lazy)."""
    try:
        from ..config import settings
        return bool(settings.mock_mode)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Team role lookup — consults the team_members table (DB mode) or the
# in-memory _session_user_cache (mock mode / tests).
# ---------------------------------------------------------------------------


# team_id -> {user_id -> Role}
_mock_team_roles: dict[str, dict[str, Role]] = {}


def mock_set_team_role(team_id: str, user_id: str, role: Role) -> None:
    """Test helper: assign a role in the in-memory mock store."""
    _mock_team_roles.setdefault(team_id, {})[user_id] = role


def mock_reset() -> None:
    """Test helper: clear the in-memory mock store."""
    _mock_team_roles.clear()


def get_user_team_role(team_id: str, user_id: str) -> Optional[Role]:
    """Return the user's Role in the given team, or None if not a member.

    In mock mode (or when the DB / table is unavailable), reads from the
    in-memory mock store populated by ``mock_set_team_role``. In DB mode
    queries the ``team_members`` table.

    Master prompt §57 — never logs the user_id (it's a PII-adjacent
    identifier; the audit log captures user_id but not as part of RBAC).
    """
    if _mock_mode():
        return _mock_team_roles.get(team_id, {}).get(user_id)

    try:
        from database.base import SessionLocal
        from database.models.schema import TeamMember

        with SessionLocal() as session:
            row = (
                session.query(TeamMember)
                .filter(TeamMember.team_id == team_id)
                .filter(TeamMember.user_id == user_id)
                .filter(TeamMember.status == "active")
                .first()
            )
            if row is None:
                return None
            try:
                return Role(row.role)
            except ValueError:
                return None
    except Exception:
        # DB unavailable — fall back to mock store so tests still work.
        return _mock_team_roles.get(team_id, {}).get(user_id)


# ---------------------------------------------------------------------------
# FastAPI dependencies — require_role / require_permission
# ---------------------------------------------------------------------------


def _team_id_from_path_or_query(
    path_team_id: Optional[str] = None,
    query_team_id: Optional[str] = None,
) -> Optional[str]:
    return path_team_id or query_team_id


def require_role(*allowed_roles: Role) -> Callable[..., Any]:
    """Build a FastAPI dependency that requires the user's team role to
    be one of ``allowed_roles``.

    The dependency inspects the path parameter ``team_id`` (and the
    query param ``team_id`` as a fallback) to look up the user's role.
    """
    allowed_set = set(allowed_roles)

    async def _dep(
        authorization: Optional[str] = Header(None),
        x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
        x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
        team_id: Optional[str] = None,
    ) -> dict[str, Any]:
        user = await get_current_user_async(
            authorization=authorization,
            x_user_id=x_user_id,
            x_user_email=x_user_email,
        )
        if not team_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "team_id path parameter is required for RBAC check",
            )
        role = get_user_team_role(team_id, user["id"])
        if role is None or role not in allowed_set:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{role.value if role else None}' is not allowed "
                f"(requires one of {[r.value for r in allowed_roles]})",
            )
        user["role"] = role
        return user

    return _dep


def require_permission(permission: Permission) -> Callable[..., Any]:
    """Build a FastAPI dependency that requires the user's team role to
    grant ``permission`` (master prompt §82 RBAC matrix).
    """
    async def _dep(
        authorization: Optional[str] = Header(None),
        x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
        x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
        team_id: Optional[str] = None,
    ) -> dict[str, Any]:
        user = await get_current_user_async(
            authorization=authorization,
            x_user_id=x_user_id,
            x_user_email=x_user_email,
        )
        if not team_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "team_id path parameter is required for RBAC check",
            )
        role = get_user_team_role(team_id, user["id"])
        if role is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        if not role_allows(role, permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{role.value}' does not grant permission "
                f"'{permission.value}'",
            )
        user["role"] = role
        return user

    return _dep


# ---------------------------------------------------------------------------
# Enterprise policy enforcement — master prompt §82
# ---------------------------------------------------------------------------


# Risk-level ordering used by the ``max_risk_level`` policy.
_RISK_ORDER: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _risk_value(risk: str) -> int:
    """Map a risk-level string to its rank (unknown → 0)."""
    return _RISK_ORDER.get((risk or "").lower(), 0)


# team_id -> {policy_type -> policy_value}
_mock_policies: dict[str, dict[str, Any]] = {}


def mock_set_policy(team_id: str, policy_type: str, value: Any) -> None:
    """Test helper: set a policy in the in-memory mock store."""
    _mock_policies.setdefault(team_id, {})[policy_type] = value


def mock_clear_policies() -> None:
    """Test helper: clear all mock policies."""
    _mock_policies.clear()


def load_team_policies(team_id: str) -> dict[str, Any]:
    """Return the active enforced policies for ``team_id`` as a dict
    ``{policy_type: policy_value}``.

    In mock mode reads the in-memory store; in DB mode queries the
    ``enterprise_policies`` table.
    """
    if _mock_mode():
        return dict(_mock_policies.get(team_id, {}))

    try:
        from database.base import SessionLocal
        from database.models.schema import EnterprisePolicy

        out: dict[str, Any] = {}
        with SessionLocal() as session:
            rows = (
                session.query(EnterprisePolicy)
                .filter(EnterprisePolicy.team_id == team_id)
                .filter(EnterprisePolicy.enforced == True)  # noqa: E712
                .all()
            )
            for r in rows:
                out[r.policy_type] = r.policy_value
        return out
    except Exception:
        return dict(_mock_policies.get(team_id, {}))


def enforce_policy(
    policy_type: str,
    value: Any,
    team_id: Optional[str] = None,
) -> bool:
    """Return True if the proposed action satisfies the team's policy.

    Master prompt §82 — enterprise policies MUST be enforced. The
    WorkflowExecutor calls this BEFORE executing a step; if it returns
    False the step is skipped + an audit log entry records the denial.

    Supported policies:

    - ``max_risk_level``       — value is the action's risk level
      (low/medium/high/critical). The policy value is the maximum
      allowed risk level. CRITICAL > HIGH > MEDIUM > LOW.

    - ``allowed_tools``        — value is the tool name. Policy value
      is a list of allowed tool names; if the tool isn't in the list,
      the action is blocked.

    - ``blocked_tools``        — value is the tool name. Policy value
      is a list of forbidden tool names; if the tool is in the list,
      the action is blocked.

    - ``allowed_domains``      — value is a URL. Policy value is a list
      of allowed domains; if the URL's host isn't in the list, the
      action is blocked.

    - ``require_approval_for`` — value is the action / tool name.
      Policy value is a list of actions that require admin approval.

    - ``max_daily_runs``       — value is the current run count for
      the day. Policy value is the maximum allowed.

    - ``data_residency``       — value is the proposed data location.
      Policy value is a list of allowed locations.

    When ``team_id`` is None, the policy check is skipped (returns
    True) — caller didn't have team context.
    """
    if team_id is None:
        return True  # no team context — nothing to enforce

    policies = load_team_policies(team_id)
    if not policies:
        return True  # no policies configured

    if policy_type not in policies:
        return True  # this policy type isn't configured

    configured = policies[policy_type]
    if configured is None:
        return True

    if policy_type == "max_risk_level":
        # value is the action's risk level; configured is the max allowed.
        if _risk_value(value) > _risk_value(configured):
            return False
        return True

    if policy_type == "allowed_tools":
        # value is the tool name; configured is the list of allowed tools.
        if isinstance(configured, list) and value not in configured:
            return False
        return True

    if policy_type == "blocked_tools":
        # value is the tool name; configured is the list of forbidden tools.
        if isinstance(configured, list) and value in configured:
            return False
        return True

    if policy_type == "allowed_domains":
        # value is the URL; configured is the list of allowed domains.
        if isinstance(configured, list):
            host = _extract_host(value)
            if host and host not in configured and not any(
                host.endswith("." + d) for d in configured
            ):
                return False
        return True

    if policy_type == "require_approval_for":
        # value is the action name; configured is the list of actions
        # that require admin approval. We don't have admin-approval state
        # here, so we BLOCK — the caller is responsible for surfacing
        # the "needs approval" state to the UI.
        if isinstance(configured, list) and value in configured:
            return False
        return True

    if policy_type == "max_daily_runs":
        # value is the current daily run count; configured is the cap.
        try:
            current = int(value)
            cap = int(configured)
            if current >= cap:
                return False
        except (TypeError, ValueError):
            return True
        return True

    if policy_type == "data_residency":
        # value is the proposed data location; configured is the list of
        # allowed locations.
        if isinstance(configured, list) and value not in configured:
            return False
        return True

    # Unknown policy type — fail-open (don't block on what we don't know).
    return True


def _extract_host(url: str) -> str:
    """Pull the hostname out of a URL (best-effort)."""
    if not isinstance(url, str):
        return ""
    u = url.strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    if "/" in u:
        u = u.split("/", 1)[0]
    if ":" in u:
        u = u.split(":", 1)[0]
    return u.lower()


# ---------------------------------------------------------------------------
# Convenience — record an audit log entry (best-effort, never raises).
# Used by the team / analytics routes so every permission decision is
# recorded per master prompt §55.
# ---------------------------------------------------------------------------


def record_audit(
    *,
    user_id: Optional[str],
    action: str,
    decision: Optional[str] = None,
    risk_level: Optional[str] = None,
    team_id: Optional[str] = None,
    task_id: Optional[str] = None,
    tool: Optional[str] = None,
    request: Optional[dict] = None,
    response: Optional[dict] = None,
) -> None:
    """Best-effort audit log write — never raises.

    Master prompt §55 — every permission decision, workflow run,
    integration use is logged. Master prompt §57 — NEVER log credentials
    (the caller must scrub the request dict before passing it).
    """
    try:
        from database.base import SessionLocal
        from database.models.schema import AuditLog

        # Defensive — scrub common credential-bearing fields from the
        # request dict before persisting (defense in depth on top of the
        # caller's own scrubbing).
        scrubbed_request = _scrub(request) if request else None
        scrubbed_response = _scrub(response) if response else None

        with SessionLocal() as session:
            entry = AuditLog(
                user_id=user_id,
                task_id=task_id,
                tool=tool,
                action=action,
                decision=decision,
                risk_level=risk_level,
                request_json=scrubbed_request,
                response_json=scrubbed_response,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(entry)
            session.commit()
    except Exception:
        # Audit log failures must NEVER break the request flow.
        return


_CREDENTIAL_KEYS = (
    "password",
    "api_key",
    "apikey",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "credential",
    "credentials",
    "authorization",
    "auth",
    "cookie",
    "session",
)


def _scrub(value: Any) -> Any:
    """Recursively replace credential-shaped keys with ``[REDACTED]``."""
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _CREDENTIAL_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Task-spec aliases (Phase 4 — master prompt §82).
#
# The canonical names in this module are ``Permission`` / ``ROLE_PERMISSIONS``
# / ``require_role`` / ``require_permission`` (added in an earlier task).
# Phase 4 task spec uses shorter names — ``Perm`` / ``ROLE_PERMS`` /
# ``require_team_role`` / ``require_perm``. We export both so callers using
# either name set work. The underlying enum / matrix / dependency factories
# are identical; the aliases are simply bound references.
# ---------------------------------------------------------------------------

# Short alias for the Permission enum.
Perm = Permission

# Short alias for the role -> permissions matrix.
ROLE_PERMS: dict[Role, frozenset[Permission]] = ROLE_PERMISSIONS


def require_team_role(min_role: Role) -> Callable[..., Any]:
    """FastAPI dependency factory — require the user's team role to be at
    least ``min_role`` in the team identified by the ``team_id`` path
    parameter (and the ``team_id`` query param as a fallback).

    Role hierarchy: OWNER > ADMIN > MEMBER > VIEWER. A user with a higher
    role satisfies a lower-role requirement (e.g. an OWNER passes a
    MEMBER gate). A user with no role on the team gets 403.

    This is a convenience wrapper around ``require_role`` that expands
    ``min_role`` to the set of all roles at or above it in the hierarchy.
    """
    hierarchy = [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.VIEWER]
    try:
        idx = hierarchy.index(min_role)
    except ValueError:
        # Unknown role — fall through to the empty set so the dependency
        # always denies (defensive).
        return require_role()
    allowed = tuple(hierarchy[: idx + 1])
    return require_role(*allowed)


def require_perm(perm: Permission) -> Callable[..., Any]:
    """Alias for ``require_permission`` — gates a route on a single
    permission (e.g. ``INVITE_MEMBERS``) per the RBAC matrix."""
    return require_permission(perm)


def role_allows_perm(role: Role, perm: Permission) -> bool:
    """Alias for ``role_allows`` — returns True if ``role`` grants ``perm``."""
    return role_allows(role, perm)

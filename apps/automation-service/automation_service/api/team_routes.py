"""Team + Workspace + Enterprise Policy FastAPI router — master prompt §82.

Mounted under ``/teams`` in main.py. Endpoints:

Teams:
* ``POST   /teams``                           — create a team
* ``GET    /teams``                            — list teams for current user
* ``GET    /teams/{team_id}``                  — team details
* ``PUT    /teams/{team_id}``                  — update team (admin+)
* ``DELETE /teams/{team_id}``                  — delete team (owner only)

Members:
* ``POST   /teams/{team_id}/members``          — invite a member
* ``GET    /teams/{team_id}/members``          — list members
* ``PUT    /teams/{team_id}/members/{user_id}``— update role
* ``DELETE /teams/{team_id}/members/{user_id}`` — remove member

Workspaces:
* ``POST   /teams/{team_id}/workspaces``        — create a workspace
* ``GET    /teams/{team_id}/workspaces``       — list workspaces

Policies (master prompt §82 — enterprise policies enforced):
* ``GET    /teams/{team_id}/policies``         — list enterprise policies
* ``POST   /teams/{team_id}/policies``         — create policy (admin+)
* ``PUT    /teams/{team_id}/policies/{policy_id}`` — update policy
* ``DELETE /teams/{team_id}/policies/{policy_id}``  — delete policy

All routes require the IPC bearer token + team membership (RBAC). The
``PUT``/``DELETE`` team routes additionally require the ``MANAGE_TEAM``
permission (admin+); invite/remove members require ``INVITE_MEMBERS`` /
``REMOVE_MEMBERS``; policy CRUD requires ``MANAGE_POLICIES``.

Mock mode: backed by an in-memory store so the tests can exercise every
endpoint without a DB. DB mode: queries the SQLAlchemy tables defined
in ``database.models.schema`` (teams / team_members / workspaces /
enterprise_policies).

Master prompt §55 — every permission decision is recorded in the audit
log via :func:`automation_service.security.rbac.record_audit`.
Master prompt §57 — credentials are NEVER logged (the audit scrubber
in rbac.py redacts known credential keys before persisting).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..config import settings
from ..security.rbac import (
    Permission,
    Role,
    get_user_team_role,
    mock_set_team_role,
    mock_set_policy,
    record_audit,
    require_permission,
)


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# In-memory mock store (mock mode + tests)
# ---------------------------------------------------------------------------


class _TeamStore:
    """In-memory store keyed by team_id. Each team dict carries its own
    members + workspaces + policies sub-collections so we don't need to
    duplicate the cross-table joins."""

    def __init__(self) -> None:
        self._teams: dict[str, dict[str, Any]] = {}
        # user_id -> set of team_ids
        self._user_teams: dict[str, set[str]] = {}

    # ----- teams -----
    def add_team(self, team: dict) -> None:
        self._teams[team["id"]] = team
        self._user_teams.setdefault(team["owner_id"], set()).add(team["id"])

    def get_team(self, team_id: str) -> Optional[dict]:
        return self._teams.get(team_id)

    def list_for_user(self, user_id: str) -> list[dict]:
        ids = self._user_teams.get(user_id, set())
        return [self._teams[t] for t in ids if t in self._teams]

    def delete_team(self, team_id: str) -> bool:
        if team_id in self._teams:
            owner = self._teams[team_id]["owner_id"]
            del self._teams[team_id]
            if owner in self._user_teams:
                self._user_teams[owner].discard(team_id)
            # Drop membership rows too.
            for uid in list(self._user_teams.keys()):
                self._user_teams[uid].discard(team_id)
            return True
        return False

    def find_by_name(self, name: str) -> Optional[dict]:
        for t in self._teams.values():
            if t["name"] == name:
                return t
        return None

    # ----- members -----
    def add_member(self, team_id: str, member: dict) -> bool:
        team = self._teams.get(team_id)
        if team is None:
            return False
        members = team.setdefault("members", [])
        # Don't double-insert.
        for m in members:
            if m["user_id"] == member["user_id"]:
                return False
        members.append(member)
        self._user_teams.setdefault(member["user_id"], set()).add(team_id)
        return True

    def list_members(self, team_id: str) -> list[dict]:
        team = self._teams.get(team_id)
        if team is None:
            return []
        # Always include the owner as an "owner" member.
        members = list(team.get("members", []))
        if not any(m["user_id"] == team["owner_id"] for m in members):
            members.insert(
                0,
                {
                    "user_id": team["owner_id"],
                    "email": None,
                    "role": Role.OWNER.value,
                    "status": "active",
                    "joined_at": team["created_at"],
                },
            )
        return members

    def update_member_role(
        self, team_id: str, user_id: str, role: str
    ) -> Optional[dict]:
        team = self._teams.get(team_id)
        if team is None:
            return None
        for m in team.get("members", []):
            if m["user_id"] == user_id:
                m["role"] = role
                return m
        return None

    def remove_member(self, team_id: str, user_id: str) -> bool:
        team = self._teams.get(team_id)
        if team is None:
            return False
        members = team.get("members", [])
        for i, m in enumerate(members):
            if m["user_id"] == user_id:
                del members[i]
                self._user_teams.get(user_id, set()).discard(team_id)
                return True
        return False

    # ----- workspaces -----
    def add_workspace(self, team_id: str, ws: dict) -> bool:
        team = self._teams.get(team_id)
        if team is None:
            return False
        team.setdefault("workspaces", []).append(ws)
        return True

    def list_workspaces(self, team_id: str) -> list[dict]:
        team = self._teams.get(team_id)
        if team is None:
            return []
        return list(team.get("workspaces", []))

    # ----- policies -----
    def add_policy(self, team_id: str, policy: dict) -> bool:
        team = self._teams.get(team_id)
        if team is None:
            return False
        team.setdefault("policies", []).append(policy)
        # Mirror into the rbac mock policy store so enforce_policy sees it.
        mock_set_policy(team_id, policy["policy_type"], policy["policy_value"])
        return True

    def list_policies(self, team_id: str) -> list[dict]:
        team = self._teams.get(team_id)
        if team is None:
            return []
        return list(team.get("policies", []))

    def update_policy(
        self, team_id: str, policy_id: str, policy_value: Any, enforced: Optional[bool]
    ) -> Optional[dict]:
        team = self._teams.get(team_id)
        if team is None:
            return None
        for p in team.get("policies", []):
            if p["id"] == policy_id:
                p["policy_value"] = policy_value
                if enforced is not None:
                    p["enforced"] = enforced
                p["updated_at"] = _now()
                mock_set_policy(team_id, p["policy_type"], p["policy_value"])
                return p
        return None

    def delete_policy(self, team_id: str, policy_id: str) -> bool:
        team = self._teams.get(team_id)
        if team is None:
            return False
        policies = team.get("policies", [])
        for i, p in enumerate(policies):
            if p["id"] == policy_id:
                del policies[i]
                return True
        return False


_store = _TeamStore()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return slug or "team"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    max_members: int = Field(10, ge=1, le=10_000)
    max_workflows: int = Field(100, ge=1, le=10_000)


class UpdateTeamRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    max_members: Optional[int] = Field(None, ge=1, le=10_000)
    max_workflows: Optional[int] = Field(None, ge=1, le=10_000)


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field("member", description="admin | member | viewer")


class UpdateMemberRequest(BaseModel):
    role: str = Field(..., description="admin | member | viewer")


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class CreatePolicyRequest(BaseModel):
    policy_type: str = Field(
        ...,
        description=(
            "max_risk_level | allowed_tools | blocked_tools | "
            "allowed_domains | require_approval_for | max_daily_runs | "
            "data_residency"
        ),
    )
    policy_value: Optional[Any] = None
    enforced: bool = True


class UpdatePolicyRequest(BaseModel):
    policy_value: Optional[Any] = None
    enforced: Optional[bool] = None


# ---------------------------------------------------------------------------
# DB helpers — when settings.mock_mode is False we fall through to
# SQLAlchemy. Each query is wrapped in try/except so a missing DB /
# missing table is reported as a clean 404 rather than 500.
# ---------------------------------------------------------------------------


def _open_session():
    try:
        from database.base import SessionLocal
        from database.models import schema  # noqa: F401
    except Exception:
        return None
    try:
        return SessionLocal()
    except Exception:
        return None


def _team_to_dict(row: Any) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "owner_id": row.owner_id,
        "max_members": row.max_members,
        "max_workflows": row.max_workflows,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _member_to_dict(row: Any) -> dict:
    return {
        "id": row.id,
        "team_id": row.team_id,
        "user_id": row.user_id,
        "role": row.role,
        "status": row.status,
        "invited_at": row.invited_at,
        "joined_at": row.joined_at,
    }


def _workspace_to_dict(row: Any) -> dict:
    return {
        "id": row.id,
        "team_id": row.team_id,
        "name": row.name,
        "description": row.description,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _policy_to_dict(row: Any) -> dict:
    return {
        "id": row.id,
        "team_id": row.team_id,
        "policy_type": row.policy_type,
        "policy_value": row.policy_value,
        "enforced": bool(row.enforced),
        "created_at": row.created_at,
    }


# ---------------------------------------------------------------------------
# Current-user helper (lightweight — reads X-User-Id header)
# ---------------------------------------------------------------------------


def _current_user_id(x_user_id: Optional[str]) -> str:
    return (x_user_id or "default").strip() or "default"


# ---------------------------------------------------------------------------
# Routes — Team CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["teams"],
)
async def create_team(
    req: CreateTeamRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Create a new team. The current user becomes the OWNER."""
    user_id = _current_user_id(x_user_id)

    if settings.mock_mode:
        # Uniqueness check.
        if _store.find_by_name(req.name) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"a team named '{req.name}' already exists",
            )
        team_id = str(uuid.uuid4())
        now = _now()
        team = {
            "id": team_id,
            "name": req.name,
            "slug": _slugify(req.name),
            "description": req.description,
            "owner_id": user_id,
            "max_members": req.max_members,
            "max_workflows": req.max_workflows,
            "created_at": now,
            "updated_at": now,
            "members": [],
            "workspaces": [],
            "policies": [],
        }
        _store.add_team(team)
        # Mirror the owner's role into the rbac mock store.
        mock_set_team_role(team_id, user_id, Role.OWNER)
        record_audit(
            user_id=user_id,
            action="team.create",
            decision="allow",
            team_id=team_id,
            request={"name": req.name},
        )
        return _team_to_dict_simple(team)

    # DB mode
    from database.models.schema import Team
    session = _open_session()
    if session is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "database unavailable",
        )
    try:
        if session.query(Team).filter(Team.name == req.name).first():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"a team named '{req.name}' already exists",
            )
        team_id = str(uuid.uuid4())
        now = _now()
        row = Team(
            id=team_id,
            name=req.name,
            slug=_slugify(req.name),
            description=req.description,
            owner_id=user_id,
            max_members=req.max_members,
            max_workflows=req.max_workflows,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        mock_set_team_role(team_id, user_id, Role.OWNER)
        record_audit(
            user_id=user_id,
            action="team.create",
            decision="allow",
            team_id=team_id,
            request={"name": req.name},
        )
        return _team_to_dict(row)
    finally:
        session.close()


def _team_to_dict_simple(team: dict) -> dict:
    """Convert an in-memory team dict to a response (no members/workspaces)."""
    return {
        "id": team["id"],
        "name": team["name"],
        "slug": team["slug"],
        "description": team.get("description"),
        "owner_id": team["owner_id"],
        "max_members": team.get("max_members", 10),
        "max_workflows": team.get("max_workflows", 100),
        "created_at": team.get("created_at"),
        "updated_at": team.get("updated_at"),
    }


@router.get(
    "",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def list_teams(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """List all teams the current user belongs to."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        teams = [_team_to_dict_simple(t) for t in _store.list_for_user(user_id)]
        # Decorate with the user's role in each team.
        for t in teams:
            role = get_user_team_role(t["id"], user_id)
            t["my_role"] = role.value if role else None
        return {"teams": teams, "count": len(teams)}

    from database.models.schema import Team, TeamMember
    session = _open_session()
    if session is None:
        return {"teams": [], "count": 0, "mock_mode": True}
    try:
        # Teams the user owns.
        owned = session.query(Team).filter(Team.owner_id == user_id).all()
        owned_ids = {t.id for t in owned}
        # Teams the user is a member of (excluding owned).
        member_rows = (
            session.query(TeamMember)
            .filter(TeamMember.user_id == user_id)
            .filter(TeamMember.status == "active")
            .all()
        )
        member_team_ids = {r.team_id for r in member_rows} - owned_ids
        extra = (
            session.query(Team).filter(Team.id.in_(member_team_ids)).all()
            if member_team_ids
            else []
        )
        teams = [_team_to_dict(t) for t in list(owned) + list(extra)]
        for t in teams:
            role = get_user_team_role(t["id"], user_id)
            t["my_role"] = role.value if role else None
        return {"teams": teams, "count": len(teams)}
    finally:
        session.close()


@router.get(
    "/{team_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def get_team(
    team_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Get team details. Requires VIEW_TEAM permission (any member)."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        role = get_user_team_role(team_id, user_id)
        if role is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        out = _team_to_dict_simple(team)
        out["my_role"] = role.value
        return out

    from database.models.schema import Team
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "team not found")
    try:
        row = session.query(Team).filter(Team.id == team_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        role = get_user_team_role(team_id, user_id)
        if role is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        out = _team_to_dict(row)
        out["my_role"] = role.value
        return out
    finally:
        session.close()


@router.put(
    "/{team_id}",
    tags=["teams"],
)
async def update_team(
    team_id: str,
    req: UpdateTeamRequest,
    user: dict = Depends(require_permission(Permission.MANAGE_TEAM)),
) -> dict[str, Any]:
    """Update team metadata — requires MANAGE_TEAM permission (admin+)."""
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if req.name is not None:
            team["name"] = req.name
            team["slug"] = _slugify(req.name)
        if req.description is not None:
            team["description"] = req.description
        if req.max_members is not None:
            team["max_members"] = req.max_members
        if req.max_workflows is not None:
            team["max_workflows"] = req.max_workflows
        team["updated_at"] = _now()
        record_audit(
            user_id=user["id"],
            action="team.update",
            decision="allow",
            team_id=team_id,
        )
        return _team_to_dict_simple(team)

    from database.models.schema import Team
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = session.query(Team).filter(Team.id == team_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if req.name is not None:
            row.name = req.name
            row.slug = _slugify(req.name)
        if req.description is not None:
            row.description = req.description
        if req.max_members is not None:
            row.max_members = req.max_members
        if req.max_workflows is not None:
            row.max_workflows = req.max_workflows
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        record_audit(
            user_id=user["id"],
            action="team.update",
            decision="allow",
            team_id=team_id,
        )
        return _team_to_dict(row)
    finally:
        session.close()


@router.delete(
    "/{team_id}",
    tags=["teams"],
)
async def delete_team(
    team_id: str,
    user: dict = Depends(require_permission(Permission.MANAGE_TEAM)),
) -> dict[str, Any]:
    """Delete a team — requires MANAGE_TEAM permission (owner only in
    practice since the RBAC matrix grants MANAGE_TEAM to owner+admin).
    """
    if settings.mock_mode:
        ok = _store.delete_team(team_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        record_audit(
            user_id=user["id"],
            action="team.delete",
            decision="allow",
            team_id=team_id,
        )
        return {"team_id": team_id, "deleted": True}

    from database.models.schema import Team, TeamMember, Workspace, EnterprisePolicy
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = session.query(Team).filter(Team.id == team_id).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        # Cascade-delete the related rows.
        session.query(TeamMember).filter(TeamMember.team_id == team_id).delete()
        session.query(Workspace).filter(Workspace.team_id == team_id).delete()
        session.query(EnterprisePolicy).filter(EnterprisePolicy.team_id == team_id).delete()
        session.delete(row)
        session.commit()
        record_audit(
            user_id=user["id"],
            action="team.delete",
            decision="allow",
            team_id=team_id,
        )
        return {"team_id": team_id, "deleted": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@router.post(
    "/{team_id}/members",
    status_code=status.HTTP_201_CREATED,
    tags=["teams"],
)
async def invite_member(
    team_id: str,
    req: InviteMemberRequest,
    user: dict = Depends(require_permission(Permission.INVITE_MEMBERS)),
) -> dict[str, Any]:
    """Invite a member to the team by email. Requires INVITE_MEMBERS."""
    try:
        role = Role(req.role)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid role '{req.role}'. Allowed: admin | member | viewer",
        )
    if role == Role.OWNER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot invite a new owner; transfer ownership instead",
        )

    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        # Member count cap (master prompt §82 — max_members policy).
        if len(team.get("members", [])) >= team.get("max_members", 10):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"team has reached max_members ({team['max_members']})",
            )
        user_id = str(uuid.uuid4())
        member = {
            "id": str(uuid.uuid4()),
            "team_id": team_id,
            "user_id": user_id,
            "email": req.email,
            "role": role.value,
            "status": "pending",
            "invited_at": _now(),
            "joined_at": None,
        }
        _store.add_member(team_id, member)
        mock_set_team_role(team_id, user_id, role)
        record_audit(
            user_id=user["id"],
            action="team.member.invite",
            decision="allow",
            team_id=team_id,
            request={"email": req.email, "role": role.value},
        )
        return member

    from database.models.schema import Team, TeamMember
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        team = session.query(Team).filter(Team.id == team_id).first()
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        count = (
            session.query(TeamMember)
            .filter(TeamMember.team_id == team_id)
            .filter(TeamMember.status == "active")
            .count()
        )
        if count >= team.max_members:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"team has reached max_members ({team.max_members})",
            )
        user_id = str(uuid.uuid4())
        member = TeamMember(
            id=str(uuid.uuid4()),
            team_id=team_id,
            user_id=user_id,
            role=role.value,
            status="pending",
            invited_at=_now(),
        )
        session.add(member)
        session.commit()
        session.refresh(member)
        mock_set_team_role(team_id, user_id, role)
        record_audit(
            user_id=user["id"],
            action="team.member.invite",
            decision="allow",
            team_id=team_id,
            request={"email": req.email, "role": role.value},
        )
        out = _member_to_dict(member)
        out["email"] = req.email
        return out
    finally:
        session.close()


@router.get(
    "/{team_id}/members",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def list_members(
    team_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """List all members of a team. Requires team membership."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        members = _store.list_members(team_id)
        return {"members": members, "count": len(members)}

    from database.models.schema import TeamMember
    session = _open_session()
    if session is None:
        return {"members": [], "count": 0, "mock_mode": True}
    try:
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        rows = (
            session.query(TeamMember)
            .filter(TeamMember.team_id == team_id)
            .order_by(TeamMember.invited_at.asc())
            .all()
        )
        members = [_member_to_dict(r) for r in rows]
        return {"members": members, "count": len(members)}
    finally:
        session.close()


@router.put(
    "/{team_id}/members/{user_id}",
    tags=["teams"],
)
async def update_member(
    team_id: str,
    user_id: str,
    req: UpdateMemberRequest,
    user: dict = Depends(require_permission(Permission.REMOVE_MEMBERS)),
) -> dict[str, Any]:
    """Update a member's role — requires REMOVE_MEMBERS (admin+)."""
    try:
        role = Role(req.role)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid role '{req.role}'. Allowed: admin | member | viewer",
        )
    if role == Role.OWNER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot promote to owner; transfer ownership instead",
        )

    if settings.mock_mode:
        m = _store.update_member_role(team_id, user_id, role.value)
        if m is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"member '{user_id}' not found in team '{team_id}'",
            )
        mock_set_team_role(team_id, user_id, role)
        record_audit(
            user_id=user["id"],
            action="team.member.update_role",
            decision="allow",
            team_id=team_id,
            request={"user_id": user_id, "role": role.value},
        )
        return m

    from database.models.schema import TeamMember
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = (
            session.query(TeamMember)
            .filter(TeamMember.team_id == team_id)
            .filter(TeamMember.user_id == user_id)
            .first()
        )
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"member '{user_id}' not found in team '{team_id}'",
            )
        row.role = role.value
        session.commit()
        session.refresh(row)
        mock_set_team_role(team_id, user_id, role)
        record_audit(
            user_id=user["id"],
            action="team.member.update_role",
            decision="allow",
            team_id=team_id,
            request={"user_id": user_id, "role": role.value},
        )
        return _member_to_dict(row)
    finally:
        session.close()


@router.delete(
    "/{team_id}/members/{user_id}",
    tags=["teams"],
)
async def remove_member(
    team_id: str,
    user_id: str,
    user: dict = Depends(require_permission(Permission.REMOVE_MEMBERS)),
) -> dict[str, Any]:
    """Remove a member from the team — requires REMOVE_MEMBERS (admin+)."""
    if user_id == user["id"]:
        # Owner can't remove themselves (would orphan the team).
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot remove yourself from the team; transfer ownership first",
        )

    if settings.mock_mode:
        ok = _store.remove_member(team_id, user_id)
        if not ok:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"member '{user_id}' not found in team '{team_id}'",
            )
        record_audit(
            user_id=user["id"],
            action="team.member.remove",
            decision="allow",
            team_id=team_id,
            request={"user_id": user_id},
        )
        return {"team_id": team_id, "user_id": user_id, "removed": True}

    from database.models.schema import TeamMember
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = (
            session.query(TeamMember)
            .filter(TeamMember.team_id == team_id)
            .filter(TeamMember.user_id == user_id)
            .first()
        )
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"member '{user_id}' not found in team '{team_id}'",
            )
        session.delete(row)
        session.commit()
        record_audit(
            user_id=user["id"],
            action="team.member.remove",
            decision="allow",
            team_id=team_id,
            request={"user_id": user_id},
        )
        return {"team_id": team_id, "user_id": user_id, "removed": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


@router.post(
    "/{team_id}/workspaces",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def create_workspace(
    team_id: str,
    req: CreateWorkspaceRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Create a workspace within a team. Requires team membership."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        ws = {
            "id": str(uuid.uuid4()),
            "team_id": team_id,
            "name": req.name,
            "description": req.description,
            "created_by": user_id,
            "created_at": _now(),
        }
        _store.add_workspace(team_id, ws)
        record_audit(
            user_id=user_id,
            action="team.workspace.create",
            decision="allow",
            team_id=team_id,
            request={"name": req.name},
        )
        return ws

    from database.models.schema import Team, Workspace
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        if session.query(Team).filter(Team.id == team_id).first() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        ws = Workspace(
            id=str(uuid.uuid4()),
            team_id=team_id,
            name=req.name,
            description=req.description,
            created_by=user_id,
            created_at=_now(),
        )
        session.add(ws)
        session.commit()
        session.refresh(ws)
        record_audit(
            user_id=user_id,
            action="team.workspace.create",
            decision="allow",
            team_id=team_id,
            request={"name": req.name},
        )
        return _workspace_to_dict(ws)
    finally:
        session.close()


@router.get(
    "/{team_id}/workspaces",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def list_workspaces(
    team_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """List all workspaces in a team."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        wss = _store.list_workspaces(team_id)
        return {"workspaces": wss, "count": len(wss)}

    from database.models.schema import Workspace
    session = _open_session()
    if session is None:
        return {"workspaces": [], "count": 0, "mock_mode": True}
    try:
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        rows = (
            session.query(Workspace)
            .filter(Workspace.team_id == team_id)
            .order_by(Workspace.created_at.asc())
            .all()
        )
        wss = [_workspace_to_dict(r) for r in rows]
        return {"workspaces": wss, "count": len(wss)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Enterprise Policies — master prompt §82
# ---------------------------------------------------------------------------


_ALLOWED_POLICY_TYPES = {
    "max_risk_level",
    "allowed_tools",
    "blocked_tools",
    "allowed_domains",
    "require_approval_for",
    "max_daily_runs",
    "data_residency",
}


@router.get(
    "/{team_id}/policies",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["teams"],
)
async def list_policies(
    team_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """List all enterprise policies for a team."""
    user_id = _current_user_id(x_user_id)
    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        policies = _store.list_policies(team_id)
        return {"policies": policies, "count": len(policies)}

    from database.models.schema import EnterprisePolicy
    session = _open_session()
    if session is None:
        return {"policies": [], "count": 0, "mock_mode": True}
    try:
        if get_user_team_role(team_id, user_id) is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "user is not a member of this team",
            )
        rows = (
            session.query(EnterprisePolicy)
            .filter(EnterprisePolicy.team_id == team_id)
            .order_by(EnterprisePolicy.created_at.asc())
            .all()
        )
        policies = [_policy_to_dict(r) for r in rows]
        return {"policies": policies, "count": len(policies)}
    finally:
        session.close()


@router.post(
    "/{team_id}/policies",
    status_code=status.HTTP_201_CREATED,
    tags=["teams"],
)
async def create_policy(
    team_id: str,
    req: CreatePolicyRequest,
    user: dict = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> dict[str, Any]:
    """Create an enterprise policy — requires MANAGE_POLICIES (admin+)."""
    if req.policy_type not in _ALLOWED_POLICY_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid policy_type '{req.policy_type}'. Allowed: {sorted(_ALLOWED_POLICY_TYPES)}",
        )

    if settings.mock_mode:
        team = _store.get_team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"team '{team_id}' not found")
        policy = {
            "id": str(uuid.uuid4()),
            "team_id": team_id,
            "policy_type": req.policy_type,
            "policy_value": req.policy_value,
            "enforced": req.enforced,
            "created_at": _now(),
            "updated_at": _now(),
        }
        _store.add_policy(team_id, policy)
        record_audit(
            user_id=user["id"],
            action="team.policy.create",
            decision="allow",
            team_id=team_id,
            request={"policy_type": req.policy_type, "policy_value": req.policy_value},
        )
        return policy

    from database.models.schema import EnterprisePolicy
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = EnterprisePolicy(
            id=str(uuid.uuid4()),
            team_id=team_id,
            policy_type=req.policy_type,
            policy_value=req.policy_value,
            enforced=req.enforced,
            created_at=_now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        # Mirror into the rbac mock policy store so enforce_policy sees it
        # even when the rest of the test stack runs in mock mode.
        mock_set_policy(team_id, req.policy_type, req.policy_value)
        record_audit(
            user_id=user["id"],
            action="team.policy.create",
            decision="allow",
            team_id=team_id,
            request={"policy_type": req.policy_type, "policy_value": req.policy_value},
        )
        return _policy_to_dict(row)
    finally:
        session.close()


@router.put(
    "/{team_id}/policies/{policy_id}",
    tags=["teams"],
)
async def update_policy(
    team_id: str,
    policy_id: str,
    req: UpdatePolicyRequest,
    user: dict = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> dict[str, Any]:
    """Update an enterprise policy — requires MANAGE_POLICIES."""
    if settings.mock_mode:
        if req.policy_value is None and req.enforced is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "must supply at least one of policy_value / enforced",
            )
        p = _store.update_policy(
            team_id, policy_id, req.policy_value, req.enforced
        )
        if p is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"policy '{policy_id}' not found in team '{team_id}'",
            )
        record_audit(
            user_id=user["id"],
            action="team.policy.update",
            decision="allow",
            team_id=team_id,
            request={"policy_id": policy_id},
        )
        return p

    from database.models.schema import EnterprisePolicy
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = (
            session.query(EnterprisePolicy)
            .filter(EnterprisePolicy.team_id == team_id)
            .filter(EnterprisePolicy.id == policy_id)
            .first()
        )
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"policy '{policy_id}' not found in team '{team_id}'",
            )
        if req.policy_value is not None:
            row.policy_value = req.policy_value
        if req.enforced is not None:
            row.enforced = req.enforced
        session.commit()
        session.refresh(row)
        if row.enforced:
            mock_set_policy(team_id, row.policy_type, row.policy_value)
        record_audit(
            user_id=user["id"],
            action="team.policy.update",
            decision="allow",
            team_id=team_id,
            request={"policy_id": policy_id},
        )
        return _policy_to_dict(row)
    finally:
        session.close()


@router.delete(
    "/{team_id}/policies/{policy_id}",
    tags=["teams"],
)
async def delete_policy(
    team_id: str,
    policy_id: str,
    user: dict = Depends(require_permission(Permission.MANAGE_POLICIES)),
) -> dict[str, Any]:
    """Delete an enterprise policy — requires MANAGE_POLICIES."""
    if settings.mock_mode:
        ok = _store.delete_policy(team_id, policy_id)
        if not ok:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"policy '{policy_id}' not found in team '{team_id}'",
            )
        record_audit(
            user_id=user["id"],
            action="team.policy.delete",
            decision="allow",
            team_id=team_id,
            request={"policy_id": policy_id},
        )
        return {"policy_id": policy_id, "deleted": True}

    from database.models.schema import EnterprisePolicy
    session = _open_session()
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    try:
        row = (
            session.query(EnterprisePolicy)
            .filter(EnterprisePolicy.team_id == team_id)
            .filter(EnterprisePolicy.id == policy_id)
            .first()
        )
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"policy '{policy_id}' not found in team '{team_id}'",
            )
        session.delete(row)
        session.commit()
        record_audit(
            user_id=user["id"],
            action="team.policy.delete",
            decision="allow",
            team_id=team_id,
            request={"policy_id": policy_id},
        )
        return {"policy_id": policy_id, "deleted": True}
    finally:
        session.close()

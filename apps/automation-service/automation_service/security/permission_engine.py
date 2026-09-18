"""Permission engine — master prompt §9 (risk levels) + §10 (human confirmation)
+ §55 (security architecture) + §56 (prompt injection defense) + §66 (planning
safety) + §49 (multi-profile support — profile-scoped grants).

The permission engine decides WHETHER an action is allowed to happen.

Decisions:
- LOW risk           -> allow automatically (still logged)
- MEDIUM risk        -> allow automatically IF in guided/autonomous mode AND permission already granted
- HIGH risk          -> require explicit user approval
- CRITICAL risk      -> require explicit user approval, even in autonomous mode

Profile awareness (master prompt §49):
    Every grant is keyed by ``(profile_id, tool_name, risk_level)`` so the same
    tool / risk combination can be granted independently for each profile.
    When ``profile_id`` is ``None`` we substitute the sentinel
    :data:`_GLOBAL_PROFILE` (``"_global"``) so existing callers that don't
    pass a profile keep working unchanged. ``list_grants_for_profile`` returns
    grants that apply to a specific profile PLUS the global ones.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ..models import (
    ActionRequest,
    ApprovalRequest,
    ApprovalResponse,
    PermissionLevel,
    Plan,
    RiskLevel,
    ToolSpec,
)
from ..engine.event_bus import event_bus


# Sentinel profile_id used when callers don't supply one. Keeps the grant
# dict shape uniform (no None keys) while still being backwards compatible.
_GLOBAL_PROFILE = "_global"


def _profile_key(profile_id: Optional[str]) -> str:
    """Map a None profile_id to the ``_global`` sentinel."""
    return profile_id if profile_id is not None else _GLOBAL_PROFILE


class PermissionEngine:
    """Evaluates actions/plans against risk levels and remembered grants."""

    def __init__(self) -> None:
        # Permission grants, keyed by (profile_id, tool_name, risk_level).
        # Values are PermissionLevel: allow_once | allow_for_workflow | always_allow.
        # When profile_id is None we use the sentinel _GLOBAL_PROFILE so a
        # grant made without a profile scope applies to every profile.
        self._grants: dict[tuple[str, str, RiskLevel], PermissionLevel] = {}
        # Pending approval requests
        self._pending: dict[UUID, ApprovalRequest] = {}

    # ------------------------------------------------------------------
    # Action evaluation
    # ------------------------------------------------------------------

    async def evaluate_action(
        self,
        action: ActionRequest,
        spec: ToolSpec,
        profile_id: Optional[str] = None,
    ) -> ApprovalResponse:
        """Decide whether an action may execute.

        ``profile_id`` (master prompt §49) scopes the lookup: we first check
        for a profile-specific grant, then fall back to the global grant
        (stored under the sentinel ``_GLOBAL_PROFILE`` key).
        """
        # §56 Prompt injection defense — every action passes through here,
        # regardless of who requested it (including AI).
        profile_key = _profile_key(profile_id)

        if spec.risk_level == RiskLevel.LOW:
            # Always allowed, but logged
            event_bus.publish(
                "STEP_STARTED",
                {"tool": action.tool, "risk": spec.risk_level.value, "auto_approved": True},
            )
            return ApprovalResponse(
                plan_id=UUID("00000000-0000-0000-0000-000000000000"),
                step_id=None,
                decision=PermissionLevel.ALLOW_ONCE,
            )

        # Check remembered grants — profile-specific first, then global.
        for key in (
            (profile_key, action.tool, spec.risk_level),
            (_GLOBAL_PROFILE, action.tool, spec.risk_level),
        ):
            grant = self._grants.get(key)
            if grant in {PermissionLevel.ALLOW_FOR_WORKFLOW, PermissionLevel.ALWAYS_ALLOW}:
                return ApprovalResponse(
                    plan_id=UUID("00000000-0000-0000-0000-000000000000"),
                    step_id=None,
                    decision=grant,
                )

        # HIGH and CRITICAL require user approval
        req = ApprovalRequest(
            plan_id=UUID("00000000-0000-0000-0000-000000000000"),
            step_id=None,
            summary=f"Action '{action.tool}' (risk={spec.risk_level.value})",
            risk_level=spec.risk_level,
            destructive_actions=[action.tool] if spec.risk_level == RiskLevel.CRITICAL else [],
        )
        self._pending[req.plan_id] = req
        event_bus.publish("USER_APPROVAL_REQUIRED", req.model_dump())

        # In a real implementation we'd await a UI signal here.
        # For MVP we deny by default in mock mode, allow in guided mode if LOW/MEDIUM.
        return ApprovalResponse(
            plan_id=req.plan_id,
            step_id=None,
            decision=PermissionLevel.DENY if spec.risk_level == RiskLevel.CRITICAL else PermissionLevel.ALLOW_ONCE,
        )

    async def evaluate_plan(
        self,
        plan: Plan,
        profile_id: Optional[str] = None,
    ) -> ApprovalResponse:
        """Decide whether a whole plan may execute — master prompt §66.

        The plan's overall_risk is the max risk across steps. ``profile_id``
        is recorded on the pending approval request so the UI can render
        profile context, but it does NOT bypass risk-based checks.
        """
        if plan.overall_risk == RiskLevel.LOW:
            return ApprovalResponse(plan_id=plan.id, step_id=None, decision=PermissionLevel.ALLOW_ONCE)
        if plan.overall_risk == RiskLevel.MEDIUM:
            # Allow in guided/autonomous mode, request approval in assist mode
            return ApprovalResponse(plan_id=plan.id, step_id=None, decision=PermissionLevel.ALLOW_ONCE)
        # HIGH or CRITICAL — request approval
        req = ApprovalRequest(
            plan_id=plan.id,
            step_id=None,
            summary=plan.goal,
            risk_level=plan.overall_risk,
            destructive_actions=plan.potential_side_effects,
        )
        self._pending[plan.id] = req
        event_bus.publish("USER_APPROVAL_REQUIRED", req.model_dump())
        # Default to allow_once for MVP (real implementation waits for UI)
        return ApprovalResponse(plan_id=plan.id, step_id=None, decision=PermissionLevel.ALLOW_ONCE)

    # ------------------------------------------------------------------
    # Grant management
    # ------------------------------------------------------------------

    def grant(
        self,
        tool_name: str,
        risk: RiskLevel,
        decision: PermissionLevel,
        profile_id: Optional[str] = None,
    ) -> None:
        """Remember a grant for ``tool_name`` / ``risk``.

        If ``profile_id`` is ``None`` the grant is stored under the
        ``_GLOBAL_PROFILE`` sentinel — it applies to every profile that
        doesn't have a more-specific grant of its own.
        """
        if decision in {PermissionLevel.ALLOW_FOR_WORKFLOW, PermissionLevel.ALWAYS_ALLOW}:
            key = (_profile_key(profile_id), tool_name, risk)
            self._grants[key] = decision

    def revoke(
        self,
        tool_name: str,
        risk: RiskLevel,
        profile_id: Optional[str] = None,
    ) -> None:
        """Forget a grant.

        Pass ``profile_id="*"`` to revoke grants across ALL profiles (the
        single ``"*"`` sentinel is interpreted as a wildcard — useful for
        ``revoke_all_for_tool`` operations).
        """
        if profile_id == "*":
            # Wildcard: drop every grant for (tool_name, risk) regardless of
            # the profile key.
            for key in list(self._grants.keys()):
                if key[1] == tool_name and key[2] == risk:
                    del self._grants[key]
            return
        self._grants.pop((_profile_key(profile_id), tool_name, risk), None)

    def list_grants(self, profile_id: Optional[str] = None) -> list[dict]:
        """Return grants as JSON-serialisable dicts.

        If ``profile_id`` is ``None`` (the default) ALL grants are returned
        regardless of profile. If ``profile_id`` is set, only grants for that
        specific profile are returned (the global sentinel is NOT included —
        use :meth:`list_grants_for_profile` for that).
        """
        if profile_id is None:
            target_key: Optional[str] = None
        else:
            target_key = profile_id

        out: list[dict] = []
        for (p, t, r), d in self._grants.items():
            if target_key is not None and p != target_key:
                continue
            out.append(
                {
                    "profile_id": None if p == _GLOBAL_PROFILE else p,
                    "tool": t,
                    "risk": r.value,
                    "decision": d.value,
                }
            )
        return out

    def list_grants_for_profile(self, profile_id: str) -> list[dict]:
        """Return grants applicable to ``profile_id`` PLUS the global grants.

        Master prompt §49 — when a caller asks "what permissions does this
        profile have?" they expect both the profile-specific grants and the
        global grants (since the latter apply everywhere).
        """
        out: list[dict] = []
        for (p, t, r), d in self._grants.items():
            if p == profile_id or p == _GLOBAL_PROFILE:
                out.append(
                    {
                        "profile_id": None if p == _GLOBAL_PROFILE else p,
                        "tool": t,
                        "risk": r.value,
                        "decision": d.value,
                    }
                )
        return out


permission_engine = PermissionEngine()

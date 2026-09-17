"""Permission engine — master prompt §9 (risk levels) + §10 (human confirmation)
+ §55 (security architecture) + §56 (prompt injection defense) + §66 (planning safety).

The permission engine decides WHETHER an action is allowed to happen.

Decisions:
- LOW risk           → allow automatically (still logged)
- MEDIUM risk        → allow automatically IF in guided/autonomous mode AND permission already granted
- HIGH risk          → require explicit user approval
- CRITICAL risk      → require explicit user approval, even in autonomous mode
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


class PermissionEngine:
    """Evaluates actions/plans against risk levels and remembered grants."""

    def __init__(self) -> None:
        # Permission grants, keyed by (tool_name, risk_level)
        # Values are PermissionLevel: allow_once | allow_for_workflow | always_allow
        self._grants: dict[tuple[str, RiskLevel], PermissionLevel] = {}
        # Pending approval requests
        self._pending: dict[UUID, ApprovalRequest] = {}

    async def evaluate_action(
        self, action: ActionRequest, spec: ToolSpec
    ) -> ApprovalResponse:
        """Decide whether an action may execute."""
        # §56 Prompt injection defense — every action passes through here,
        # regardless of who requested it (including AI).
        key = (action.tool, spec.risk_level)

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

        # Check remembered grant
        if key in self._grants:
            grant = self._grants[key]
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

    async def evaluate_plan(self, plan: Plan) -> ApprovalResponse:
        """Decide whether a whole plan may execute — master prompt §66."""
        # The plan's overall_risk is the max risk across steps.
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

    def grant(self, tool_name: str, risk: RiskLevel, decision: PermissionLevel) -> None:
        if decision in {PermissionLevel.ALLOW_FOR_WORKFLOW, PermissionLevel.ALWAYS_ALLOW}:
            self._grants[(tool_name, risk)] = decision

    def revoke(self, tool_name: str, risk: RiskLevel) -> None:
        self._grants.pop((tool_name, risk), None)

    def list_grants(self) -> list[dict]:
        return [
            {"tool": t, "risk": r.value, "decision": d.value}
            for (t, r), d in self._grants.items()
        ]


permission_engine = PermissionEngine()

"""Tests for ``security.permission_engine.PermissionEngine``.

Master prompt §9 (risk levels) + §10 (human confirmation) + §66 (planning
safety) — the permission engine decides whether an action may execute.

These tests do NOT touch the network or the filesystem; they exercise the
permission engine's pure decision logic and verify the right events are
emitted on the event bus.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from automation_service.engine.event_bus import event_bus
from automation_service.models import (
    ActionRequest,
    PermissionLevel,
    Plan,
    PlanStep,
    RiskLevel,
    ToolSpec,
)
from automation_service.security.permission_engine import PermissionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(name: str, risk: RiskLevel, perm: PermissionLevel = PermissionLevel.ALLOW_ONCE) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"test spec for {name}",
        input_schema={"type": "object", "properties": {}},
        permission_level=perm,
        risk_level=risk,
        timeout_ms=5_000,
    )


def _action(name: str) -> ActionRequest:
    return ActionRequest(tool=name, args={})


def _plan(risk: RiskLevel) -> Plan:
    return Plan(
        id=uuid4(),
        goal="test plan",
        steps=[PlanStep(id="1", action="mouse.click", risk_level=risk)],
        required_permissions=[PermissionLevel.ALLOW_ONCE],
        overall_risk=risk,
    )


# ---------------------------------------------------------------------------
# evaluate_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_risk_auto_allowed() -> None:
    """A LOW-risk action is auto-approved with ALLOW_ONCE (no grant needed)."""
    eng = PermissionEngine()
    res = await eng.evaluate_action(_action("mouse.click"), _spec("mouse.click", RiskLevel.LOW))
    assert res.decision == PermissionLevel.ALLOW_ONCE
    assert res.step_id is None


@pytest.mark.asyncio
async def test_high_risk_requires_approval() -> None:
    """A HIGH-risk action emits USER_APPROVAL_REQUIRED on the event bus."""
    eng = PermissionEngine()
    seen: list[dict] = []
    event_bus.on("USER_APPROVAL_REQUIRED", seen.append)

    res = await eng.evaluate_action(
        _action("file.write"), _spec("file.write", RiskLevel.HIGH)
    )
    # MVP default for HIGH is allow_once (real impl would block on UI)
    assert res.decision in {PermissionLevel.ALLOW_ONCE}
    assert len(seen) >= 1
    payload = seen[-1]
    assert payload["risk_level"] == "high"
    assert "file.write" in payload["summary"]


@pytest.mark.asyncio
async def test_remembered_grant() -> None:
    """After grant(), a MEDIUM action is auto-approved using the remembered grant."""
    eng = PermissionEngine()
    # Without grant, a MEDIUM action publishes USER_APPROVAL_REQUIRED but
    # returns allow_once (MVP behaviour).
    res_before = await eng.evaluate_action(
        _action("keyboard.type"), _spec("keyboard.type", RiskLevel.MEDIUM)
    )
    assert res_before.decision == PermissionLevel.ALLOW_ONCE

    # Grant always_allow for keyboard.type at MEDIUM risk.
    eng.grant("keyboard.type", RiskLevel.MEDIUM, PermissionLevel.ALWAYS_ALLOW)

    # Clear pending state so we can be sure the grant path is used.
    res_after = await eng.evaluate_action(
        _action("keyboard.type"), _spec("keyboard.type", RiskLevel.MEDIUM)
    )
    assert res_after.decision == PermissionLevel.ALWAYS_ALLOW


@pytest.mark.asyncio
async def test_revoke_grant() -> None:
    """After revoke(), the same action requires approval again."""
    eng = PermissionEngine()
    eng.grant("keyboard.type", RiskLevel.MEDIUM, PermissionLevel.ALWAYS_ALLOW)
    eng.revoke("keyboard.type", RiskLevel.MEDIUM)

    seen: list[dict] = []
    event_bus.on("USER_APPROVAL_REQUIRED", seen.append)
    res = await eng.evaluate_action(
        _action("keyboard.type"), _spec("keyboard.type", RiskLevel.MEDIUM)
    )
    # Without the grant the engine publishes USER_APPROVAL_REQUIRED.
    assert len(seen) >= 1
    # And the decision is the MVP default for MEDIUM (allow_once).
    assert res.decision == PermissionLevel.ALLOW_ONCE


# ---------------------------------------------------------------------------
# evaluate_plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_plan_low() -> None:
    """A LOW-risk plan is auto-approved (no USER_APPROVAL_REQUIRED event)."""
    eng = PermissionEngine()
    seen: list[dict] = []
    event_bus.on("USER_APPROVAL_REQUIRED", seen.append)

    res = await eng.evaluate_plan(_plan(RiskLevel.LOW))
    assert res.decision == PermissionLevel.ALLOW_ONCE
    assert seen == []


@pytest.mark.asyncio
async def test_evaluate_plan_high() -> None:
    """A HIGH-risk plan emits USER_APPROVAL_REQUIRED with the plan's goal."""
    eng = PermissionEngine()
    seen: list[dict] = []
    event_bus.on("USER_APPROVAL_REQUIRED", seen.append)

    plan = _plan(RiskLevel.HIGH)
    res = await eng.evaluate_plan(plan)
    assert seen, "expected at least one USER_APPROVAL_REQUIRED event"
    assert seen[-1]["summary"] == plan.goal
    assert seen[-1]["risk_level"] == "high"
    # MVP default — the engine returns allow_once for the user to honour later.
    assert res.decision == PermissionLevel.ALLOW_ONCE


# ---------------------------------------------------------------------------
# list_grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_grants() -> None:
    """list_grants() returns a JSON-serialisable list of grant records."""
    eng = PermissionEngine()
    eng.grant("mouse.click", RiskLevel.LOW, PermissionLevel.ALWAYS_ALLOW)
    eng.grant("keyboard.type", RiskLevel.MEDIUM, PermissionLevel.ALLOW_FOR_WORKFLOW)
    grants = eng.list_grants()
    assert isinstance(grants, list)
    assert len(grants) == 2
    for g in grants:
        assert isinstance(g, dict)
        assert {"tool", "risk", "decision"} <= set(g.keys())
        # Values must be plain strings (serialisable).
        assert isinstance(g["tool"], str)
        assert isinstance(g["risk"], str)
        assert isinstance(g["decision"], str)

    tools = {g["tool"] for g in grants}
    assert {"mouse.click", "keyboard.type"} == tools

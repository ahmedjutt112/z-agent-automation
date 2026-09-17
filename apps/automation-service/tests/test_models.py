"""Unit tests for the Pydantic domain models in ``automation_service.models``.

These tests do NOT touch the filesystem, the network, or the FastAPI app —
they validate the Pydantic schemas and enums in isolation. They run in mock
mode by default (the autouse ``mock_settings`` fixture in conftest.py pins
``settings.mock_mode=True``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from automation_service.models import (
    ActionRequest,
    ActionResult,
    AutomationMode,
    AgentRole,
    PermissionLevel,
    Plan,
    PlanStep,
    RiskLevel,
    StepStatus,
    TaskStatus,
    TriggerType,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
)


# ---------------------------------------------------------------------------
# PlanStep / Plan serialization
# ---------------------------------------------------------------------------


def test_plan_step_serialization() -> None:
    """PlanStep.model_dump() round-trips through PlanStep.model_validate()."""
    step = PlanStep(
        id="1",
        action="browser.navigate",
        args={"url": "https://example.com"},
        risk_level=RiskLevel.LOW,
        confidence=0.92,
        timeout_ms=15_000,
        retry_count=2,
        fallback="screen.ocr",
        verification="title_contains:Example",
    )
    data = step.model_dump()
    # The risk_level enum serialises to its string value.
    assert data["risk_level"] == "low"
    assert data["fallback"] == "screen.ocr"

    rebuilt = PlanStep.model_validate(data)
    assert rebuilt == step


def test_plan_validation() -> None:
    """A Plan with every field set validates cleanly."""
    plan = Plan(
        id=uuid4(),
        goal="Open Chrome and search for AI automation",
        steps=[
            PlanStep(id="1", action="app.launch", args={"app": "chrome"}),
            PlanStep(id="2", action="browser.navigate", args={"url": "https://google.com"}),
            PlanStep(id="3", action="browser.type", args={"selector": "input[name=q]", "text": "AI automation"}),
            PlanStep(id="4", action="screen.capture", args={}),
        ],
        required_permissions=[PermissionLevel.ALLOW_ONCE],
        overall_risk=RiskLevel.MEDIUM,
        potential_side_effects=["opens a browser", "submits a search query"],
        estimated_duration_seconds=45,
        variables={"target_url": "https://google.com"},
    )
    assert plan.overall_risk == RiskLevel.MEDIUM
    assert len(plan.steps) == 4
    assert plan.required_permissions == [PermissionLevel.ALLOW_ONCE]
    assert plan.potential_side_effects[0] == "opens a browser"


def test_plan_step_invalid_risk_rejected() -> None:
    """Passing an unknown risk level should raise ValidationError."""
    with pytest.raises(ValidationError):
        PlanStep(id="x", action="mouse.click", risk_level="catastrophic")  # type: ignore[arg-type]


def test_plan_step_invalid_confidence_rejected() -> None:
    """Confidence must be 0..1."""
    with pytest.raises(ValidationError):
        PlanStep(id="x", action="mouse.click", confidence=1.5)


# ---------------------------------------------------------------------------
# Workflow validation
# ---------------------------------------------------------------------------


def test_workflow_validation() -> None:
    """A Workflow with a trigger and two nodes validates cleanly."""
    wf = Workflow(
        id="wf-test-1",
        name="Open browser and screenshot",
        version=2,
        description="Regression test workflow",
        trigger=WorkflowTrigger(type=TriggerType.HOTKEY, hotkey="ctrl+shift+s"),
        nodes=[
            WorkflowNode(id="n1", type="browser.open", args={"browser": "chromium"}),
            WorkflowNode(id="n2", type="browser.navigate", args={"url": "https://example.com"}, next=None),
        ],
        variables={"site": "example.com"},
        enabled=True,
    )
    assert wf.id == "wf-test-1"
    assert wf.trigger.type == TriggerType.HOTKEY
    assert wf.trigger.hotkey == "ctrl+shift+s"
    assert len(wf.nodes) == 2
    assert wf.nodes[0].next is None
    assert wf.version == 2


def test_workflow_defaults_trigger_to_manual() -> None:
    """When no trigger is given, default to MANUAL."""
    wf = Workflow(id="wf-2", name="No trigger", nodes=[])
    assert wf.trigger.type == TriggerType.MANUAL
    assert wf.enabled is True


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_risk_level_enum() -> None:
    """RiskLevel exposes LOW / MEDIUM / HIGH / CRITICAL."""
    values = {r.value for r in RiskLevel}
    assert values == {"low", "medium", "high", "critical"}
    # str-enum: instances compare equal to their string values
    assert RiskLevel.LOW == "low"


def test_permission_level_enum() -> None:
    """PermissionLevel exposes exactly the 6 decision types from §10."""
    values = {p.value for p in PermissionLevel}
    assert values == {
        "none",
        "allow_once",
        "allow_for_workflow",
        "always_allow",
        "deny",
        "cancel",
    }


def test_aux_enums_present() -> None:
    """Sanity check: the other 5 enums have the expected members."""
    assert {t.value for t in TaskStatus} == {
        "pending", "planned", "awaiting_approval", "running",
        "paused", "completed", "failed", "cancelled",
    }
    assert {s.value for s in StepStatus} == {
        "not_started", "running", "awaiting_approval",
        "completed", "failed", "skipped", "cancelled",
    }
    assert {t.value for t in TriggerType} == {
        "schedule", "file", "application", "browser",
        "hotkey", "webhook", "system", "manual",
    }
    assert {a.value for a in AgentRole} == {
        "planner", "executor", "observer", "verification", "recovery",
    }
    assert {m.value for m in AutomationMode} == {"assist", "guided", "autonomous"}


# ---------------------------------------------------------------------------
# ActionRequest / ActionResult defaults
# ---------------------------------------------------------------------------


def test_action_request_defaults() -> None:
    """ActionRequest with just 'tool' validates and defaults args={}."""
    req = ActionRequest(tool="mouse.click")
    assert req.tool == "mouse.click"
    assert req.args == {}
    assert req.confidence == 1.0
    assert req.reason is None


def test_action_request_requires_tool() -> None:
    """Omitting 'tool' should raise."""
    with pytest.raises(ValidationError):
        ActionRequest()  # type: ignore[call-arg]


def test_action_result_status() -> None:
    """ActionResult with status=completed validates; started_at defaults."""
    res = ActionResult(tool="screen.capture", status=StepStatus.COMPLETED)
    assert res.status == StepStatus.COMPLETED
    assert res.error is None
    assert isinstance(res.started_at, datetime)
    # started_at should be timezone-aware UTC.
    assert res.started_at.tzinfo is not None


def test_action_result_failed_with_error() -> None:
    """A failed ActionResult carries an error string."""
    res = ActionResult(
        tool="file.read",
        status=StepStatus.FAILED,
        error="permission denied: /etc/passwd",
    )
    assert res.status == StepStatus.FAILED
    assert "permission denied" in (res.error or "")

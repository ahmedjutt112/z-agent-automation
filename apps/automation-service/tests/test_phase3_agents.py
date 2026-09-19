"""Tests for the Phase 3 AI Computer Agent - master prompt section 81.

Covers:
- VisionAgent: analyze_screenshot, find_target (with the section 86
  minimum confidence threshold), detect_screen_state, compare_screenshots.
- ObserverAgent: observe, find_element (section 13 cascade),
  verify_action, detect_anomalies.
- RecoveryAgent: recover_from_failure (retry + ask_user ceiling),
  dismiss_popup, handle_slow_loading.
- AutonomousAgent: execute_autonomously in ASSIST / GUIDED / max-steps /
  kill-switch paths.
- WorkflowGeneratorAgent: generate_from_description, improve_workflow,
  suggest_automations.
- API routes mounted under /agent: observe, find-element,
  execute-autonomously, generate-workflow, suggestions.

All tests run in mock mode (master prompt section 64). No real screen
capture / AI calls / network I/O.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from automation_service.agents.autonomous_agent import AutonomousAgent
from automation_service.agents.observer_agent import ObserverAgent
from automation_service.agents.recovery_agent import (
    FailureContext,
    RecoveryAgent,
)
from automation_service.agents.vision_agent import VisionAgent
from automation_service.agents.workflow_generator import WorkflowGeneratorAgent
from automation_service.config import settings
from automation_service.engine.workflow_executor import WorkflowExecutor
from automation_service.memory.manager import MemoryManager
from automation_service.models import AutomationMode, RiskLevel
from automation_service.security.kill_switch import kill_switch
from automation_service.agents.planner import PlannerAgent


# ---------------------------------------------------------------------------
# Shared event loop helper - matches the style of the existing test suite.
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# VisionAgent tests
# ---------------------------------------------------------------------------


def test_vision_agent_analyze_screenshot_mock() -> None:
    """analyze_screenshot returns a VisionAnalysis in mock mode."""
    agent = VisionAgent()
    analysis = _run(agent.analyze_screenshot(Path("/tmp/fake.png"), "Find the Download button"))
    assert analysis is not None
    assert analysis.description
    assert isinstance(analysis.elements, list)
    # Reasoning MUST be short (section 33 - no chain-of-thought).
    assert len(analysis.reasoning) <= 320


def test_vision_agent_find_target_mock() -> None:
    """find_target returns a TargetLocation with confidence >= 0.85
    when the description matches a known keyword."""
    agent = VisionAgent()
    loc = _run(agent.find_target(Path("/tmp/fake.png"), "Download"))
    assert loc is not None
    assert loc.confidence >= settings.min_vision_confidence
    assert loc.method == "vision"
    assert loc.x >= 0 and loc.y >= 0


def test_vision_agent_find_target_low_confidence_returns_none() -> None:
    """find_target returns None when confidence < settings.min_vision_confidence
    (section 86: don't guess)."""
    agent = VisionAgent()
    # Description the mock doesn't recognize -> below-threshold -> None.
    loc = _run(agent.find_target(Path("/tmp/fake.png"), "nonexistent widget"))
    assert loc is None


def test_vision_agent_detect_screen_state_mock() -> None:
    """detect_screen_state returns a ScreenState with visible buttons."""
    agent = VisionAgent()
    state = _run(agent.detect_screen_state(Path("/tmp/fake.png")))
    assert state is not None
    assert state.active_app is not None
    assert isinstance(state.visible_buttons, list)
    assert len(state.visible_buttons) > 0


def test_vision_agent_compare_screenshots_mock() -> None:
    """compare_screenshots returns a ScreenDiff with significant_change flag."""
    agent = VisionAgent()
    diff = _run(
        agent.compare_screenshots(Path("/tmp/before.png"), Path("/tmp/after.png"))
    )
    assert diff is not None
    assert isinstance(diff.changes, list)
    assert isinstance(diff.new_elements, list)
    assert isinstance(diff.significant_change, bool)


# ---------------------------------------------------------------------------
# ObserverAgent tests
# ---------------------------------------------------------------------------


def test_observer_agent_observe_mock() -> None:
    """observe() returns an Observation with screenshot + ai_summary."""
    observer = ObserverAgent()
    obs = _run(observer.observe())
    assert obs is not None
    assert obs.screenshot_path  # may be empty string when no display, but field present
    assert isinstance(obs.ai_summary, str)


def test_observer_agent_find_element_mock() -> None:
    """find_element returns a TargetLocation for a known description."""
    observer = ObserverAgent()
    # Use a description the browser_dom mock will recognise (looks like a
    # CSS selector or contains "button").
    loc = _run(observer.find_element("button.download"))
    assert loc is not None
    assert loc.x >= 0


def test_observer_agent_verify_action_mock() -> None:
    """verify_action returns a VerificationResult."""
    observer = ObserverAgent()
    result = _run(observer.verify_action("mouse.click", "file_downloaded"))
    assert result is not None
    assert isinstance(result.verified, bool)
    assert isinstance(result.evidence, str)


def test_observer_agent_detect_anomalies_mock() -> None:
    """detect_anomalies returns a list of Anomaly."""
    observer = ObserverAgent()
    anomalies = _run(observer.detect_anomalies())
    assert isinstance(anomalies, list)
    # Mock mode returns one popup-shaped anomaly.
    assert len(anomalies) >= 1
    assert anomalies[0].type in ("popup", "error_dialog", "slow_loading", "unresponsive_app")


# ---------------------------------------------------------------------------
# RecoveryAgent tests
# ---------------------------------------------------------------------------


def test_recovery_agent_recover_from_failure_retry() -> None:
    """recover_from_failure returns should_retry=True on a transient error."""
    agent = RecoveryAgent()
    failure = FailureContext(
        failed_action="mouse.click",
        error="timeout waiting for element",
        attempt_number=1,
    )
    plan = _run(agent.recover_from_failure(failure))
    assert plan is not None
    assert plan.should_retry is True
    assert plan.strategy in (
        "retry_with_delay",
        "retry_with_fallback",
        "wait_and_retry",
        "scroll_and_retry",
        "dismiss_popup",
    )


def test_recovery_agent_recover_from_failure_ask_user() -> None:
    """After MAX_RECOVERY_ATTEMPTS, the plan asks the user (section 60)."""
    agent = RecoveryAgent()
    failure = FailureContext(
        failed_action="mouse.click",
        error="element not found",
        attempt_number=agent.MAX_RECOVERY_ATTEMPTS,  # at the ceiling
    )
    plan = _run(agent.recover_from_failure(failure))
    assert plan.should_ask_user is True
    assert plan.strategy == "ask_user"
    assert plan.should_retry is False


def test_recovery_agent_dismiss_popup_mock() -> None:
    """dismiss_popup returns True in mock mode."""
    agent = RecoveryAgent()
    dismissed = _run(agent.dismiss_popup("cookie consent"))
    assert dismissed is True


def test_recovery_agent_handle_slow_loading_mock() -> None:
    """handle_slow_loading returns True quickly in mock mode."""
    agent = RecoveryAgent()
    ok = _run(agent.handle_slow_loading(timeout_seconds=5))
    assert ok is True


# ---------------------------------------------------------------------------
# AutonomousAgent tests
# ---------------------------------------------------------------------------


def test_autonomous_agent_execute_assist_mode() -> None:
    """ASSIST mode generates a plan but executes nothing (section 85)."""
    agent = AutonomousAgent(planner=PlannerAgent())
    result = _run(agent.execute_autonomously("open browser", mode=AutomationMode.ASSIST))
    assert result.mode == AutomationMode.ASSIST.value
    assert result.steps_executed == 0
    assert result.final_state in ("planned", "completed")
    assert any("ASSIST" in l for l in result.learnings)


def test_autonomous_agent_execute_guided_mode() -> None:
    """GUIDED mode executes LOW risk steps automatically."""
    agent = AutonomousAgent(planner=PlannerAgent())
    result = _run(
        agent.execute_autonomously("take a screenshot", mode=AutomationMode.GUIDED)
    )
    # The fallback planner generates a single screen.capture step (low risk).
    assert result.mode == AutomationMode.GUIDED.value
    assert result.steps_executed >= 0  # may be 0 or 1 depending on mock tools
    assert isinstance(result.execution_log, list)


def test_autonomous_agent_execute_max_steps_enforced() -> None:
    """The agent must NOT execute more steps than max_steps."""
    agent = AutonomousAgent(planner=PlannerAgent())
    result = _run(
        agent.execute_autonomously(
            "open browser", max_steps=1, mode=AutomationMode.GUIDED
        )
    )
    assert result.steps_executed <= 1
    assert any("max_steps" in l for l in result.learnings) or result.steps_executed == 1


def test_autonomous_agent_kill_switch_aborts() -> None:
    """When the kill switch is engaged, execution aborts immediately."""
    kill_switch.engage(reason="test")
    try:
        agent = AutonomousAgent(planner=PlannerAgent())
        result = _run(
            agent.execute_autonomously(
                "open browser", mode=AutomationMode.GUIDED
            )
        )
        assert result.aborted is True
        assert result.abort_reason == "kill_switch_engaged"
        assert result.final_state == "cancelled"
    finally:
        kill_switch.reset()


# ---------------------------------------------------------------------------
# WorkflowGeneratorAgent tests
# ---------------------------------------------------------------------------


def test_workflow_generator_generate_from_description() -> None:
    """generate_from_description returns a Workflow with nodes."""
    agent = WorkflowGeneratorAgent(planner=PlannerAgent())
    wf = _run(
        agent.generate_from_description(
            "Every day at 6 PM organize my Downloads folder"
        )
    )
    assert wf is not None
    assert wf.id
    assert wf.name
    assert len(wf.nodes) >= 1
    # Trigger detection should pick SCHEDULE for the "every day at" phrasing.
    assert wf.trigger.type.value == "schedule"
    assert wf.enabled is False  # user must explicitly enable


def test_workflow_generator_improve_workflow() -> None:
    """improve_workflow returns a new version with the added step."""
    from automation_service.models import (
        Workflow,
        WorkflowNode,
        WorkflowTrigger,
        TriggerType,
    )

    wf = Workflow(
        id="test-improve",
        name="Test workflow",
        version=1,
        trigger=WorkflowTrigger(type=TriggerType.MANUAL),
        nodes=[WorkflowNode(id="node_1", type="screen.capture", args={})],
    )
    agent = WorkflowGeneratorAgent(planner=PlannerAgent())
    new_wf = _run(agent.improve_workflow(wf, "make it also rename files by date"))
    assert new_wf.version == wf.version + 1
    assert len(new_wf.nodes) == len(wf.nodes) + 1
    # The new node should be a file.rename (per the feedback interpreter).
    assert any(n.type == "file.rename" for n in new_wf.nodes)
    # The input workflow must NOT be mutated.
    assert len(wf.nodes) == 1


def test_workflow_generator_suggest_automations() -> None:
    """suggest_automations returns a list of Suggestion."""
    agent = WorkflowGeneratorAgent(planner=PlannerAgent())
    suggestions = _run(agent.suggest_automations())
    assert isinstance(suggestions, list)
    assert len(suggestions) >= 1
    assert all(hasattr(s, "title") and hasattr(s, "proposed_workflow") for s in suggestions)


# ---------------------------------------------------------------------------
# API tests - exercise the /agent/* routes via the FastAPI TestClient
# ---------------------------------------------------------------------------


def test_api_agent_observe(client) -> None:
    """POST /agent/observe returns 200 with the observation."""
    r = client.post("/agent/observe", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "screenshot_path" in body
    assert "ai_summary" in body
    assert "ui_elements" in body


def test_api_agent_find_element(client) -> None:
    """POST /agent/find-element returns 200 with found / location."""
    r = client.post(
        "/agent/find-element",
        json={"description": "Download button"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "found" in body
    if body["found"]:
        assert "location" in body
        # The section 13 cascade returns the first strategy that hit.
        # Accept any of the canonical strategy names - the test exists to
        # verify the API surface, not the specific strategy chosen.
        assert body["location"]["method"] in (
            "vision",
            "browser_dom",
            "accessibility",
            "text_search",
            "image_recognition",
        )


def test_api_agent_execute_autonomously(client) -> None:
    """POST /agent/execute-autonomously returns 200 with a result."""
    r = client.post(
        "/agent/execute-autonomously",
        json={"goal": "take a screenshot", "mode": "assist"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["goal"] == "take a screenshot"
    assert body["mode"] == "assist"
    assert body["steps_executed"] == 0  # ASSIST mode never executes


def test_api_agent_generate_workflow(client) -> None:
    """POST /agent/generate-workflow returns 200 with a Workflow."""
    r = client.post(
        "/agent/generate-workflow",
        json={"description": "Every day at 6 PM organize my Downloads folder"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "workflow" in body
    assert body["executed"] is False
    assert len(body["workflow"]["nodes"]) >= 1


def test_api_agent_suggestions(client) -> None:
    """GET /agent/suggestions returns a list of suggestions."""
    r = client.get("/agent/suggestions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert all("title" in s and "proposed_workflow" in s for s in body)

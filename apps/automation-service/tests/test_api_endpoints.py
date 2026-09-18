"""Tests for the FastAPI endpoints in ``automation_service.main``.

All tests run via the ``client`` fixture (FastAPI TestClient) in mock mode.
No real mouse / keyboard / browser I/O is performed.
"""

from __future__ import annotations

import pytest

from automation_service.config import settings
from automation_service.security.kill_switch import kill_switch


# ---------------------------------------------------------------------------
# Health & tool registry
# ---------------------------------------------------------------------------


def test_health(client) -> None:
    """GET /health returns 200 with status=ok and mock_mode=true."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == settings.service_name
    assert body["mock_mode"] is True
    assert "kill_switch" in body
    assert body["kill_switch"] is False  # disengaged at start


def test_list_tools(client) -> None:
    """GET /tools returns at least 18 tool specs."""
    r = client.get("/tools")
    assert r.status_code == 200
    tools = r.json()
    assert isinstance(tools, list)
    assert len(tools) >= 18
    names = {t["name"] for t in tools}
    # Spot-check one tool from each family
    assert "mouse.click" in names
    assert "keyboard.type" in names
    assert "screen.capture" in names
    assert "file.read" in names
    assert "app.launch" in names
    assert "browser.navigate" in names


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_emergency_stop(client) -> None:
    """POST /emergency-stop engages the kill switch and returns engaged=true."""
    r = client.post("/emergency-stop")
    assert r.status_code == 200
    body = r.json()
    assert body["engaged"] is True
    assert kill_switch.engaged is True


def test_emergency_reset(client) -> None:
    """POST /emergency-reset disengages the kill switch."""
    # Engage first
    client.post("/emergency-stop")
    assert kill_switch.engaged is True
    # Then reset
    r = client.post("/emergency-reset")
    assert r.status_code == 200
    body = r.json()
    assert body["engaged"] is False
    assert kill_switch.engaged is False


def test_emergency_stop_blocks_plan(client) -> None:
    """When the kill switch is engaged, POST /task/plan returns 409."""
    client.post("/emergency-stop")
    r = client.post("/task/plan", params={"goal": "take a screenshot"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


def test_save_workflow(client, tmp_workflows_dir) -> None:
    """POST /workflow saves a workflow JSON file under workflows_dir."""
    wf = {
        "id": "test-wf-api-1",
        "name": "API Test Workflow",
        "version": 1,
        "nodes": [
            {"id": "n1", "type": "screen.capture", "args": {}},
        ],
    }
    r = client.post("/workflow", json=wf)
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["id"] == "test-wf-api-1"
    # Verify the file exists
    assert (tmp_workflows_dir / "test-wf-api-1.json").exists()


def test_list_workflows(client, tmp_workflows_dir) -> None:
    """GET /workflow returns the saved workflow summary."""
    # Save a workflow first
    wf = {
        "id": "test-wf-api-2",
        "name": "Listed Workflow",
        "version": 3,
        "nodes": [{"id": "n1", "type": "mouse.click", "args": {"x": 0, "y": 0}}],
    }
    client.post("/workflow", json=wf)
    r = client.get("/workflow")
    assert r.status_code == 200
    items = r.json()
    assert any(item["id"] == "test-wf-api-2" for item in items)
    matched = next(i for i in items if i["id"] == "test-wf-api-2")
    assert matched["name"] == "Listed Workflow"
    assert matched["version"] == 3
    assert matched["enabled"] is True


# ---------------------------------------------------------------------------
# Automation primitives (mock mode)
# ---------------------------------------------------------------------------


def test_automation_click_mock(client, tmp_screenshots_dir) -> None:
    """POST /automation/click returns ActionResult with status=completed."""
    r = client.post("/automation/click", params={"x": 42, "y": 99})
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "mouse.click"
    assert body["status"] == "completed"
    assert body["output"]["simulated"] is True
    assert body["output"]["x"] == 42
    assert body["output"]["y"] == 99


def test_automation_type_mock(client, tmp_screenshots_dir) -> None:
    """POST /automation/type returns ActionResult with the typed text echoed."""
    r = client.post("/automation/type", params={"text": "hello pytest"})
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "keyboard.type"
    assert body["status"] == "completed"
    assert body["output"]["simulated"] is True
    assert body["output"]["text"] == "hello pytest"


def test_automation_screenshot_mock(client, tmp_screenshots_dir) -> None:
    """POST /automation/screenshot returns ActionResult with a file path."""
    r = client.post("/automation/screenshot")
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "screen.capture"
    assert body["status"] == "completed"
    assert body["output"]["simulated"] is True
    # The path should be under the redirected screenshots_dir
    path = body["output"]["path"]
    assert path.startswith(str(tmp_screenshots_dir))


# ---------------------------------------------------------------------------
# Planning & execution
# ---------------------------------------------------------------------------


def test_create_plan_no_provider(client) -> None:
    """POST /task/plan with a goal returns a Plan via the fallback planner
    (no OPENAI_API_KEY is set in the test environment)."""
    r = client.post("/task/plan", params={"goal": "take a screenshot"})
    assert r.status_code == 200
    plan = r.json()
    assert plan["goal"] == "take a screenshot"
    assert isinstance(plan["steps"], list)
    assert len(plan["steps"]) >= 1
    assert plan["steps"][0]["action"] == "screen.capture"
    assert plan["overall_risk"] == "low"


def test_run_plan_mock(client, tmp_screenshots_dir) -> None:
    """POST /task/run with a simple Plan returns a run_id and executes in mock mode."""
    plan = {
        "id": "00000000-0000-0000-0000-000000000abc",
        "goal": "screenshot via plan",
        "steps": [
            {"id": "1", "action": "screen.capture", "args": {"filename": "api_run.png"}},
        ],
        "required_permissions": ["allow_once"],
        "overall_risk": "low",
    }
    r = client.post("/task/run", json=plan)
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert body["plan_id"] == plan["id"]
    # The screenshot file should exist after the run.
    assert (tmp_screenshots_dir / "api_run.png").exists()


def test_cancel_unknown_run(client) -> None:
    """POST /task/cancel/{run_id} on an unknown run_id still returns 200."""
    r = client.post("/task/cancel/does-not-exist")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["run_id"] == "does-not-exist"

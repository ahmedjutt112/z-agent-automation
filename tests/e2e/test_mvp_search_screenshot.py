"""MVP success test (mock-mode version) — master prompt section 79.

Goal: "Open Chrome, go to Google, search for AI automation, take a
screenshot, save to Desktop, notify when finished."

This test exercises the full /task/plan -> /task/run pipeline against the
mock-mode automation service. No real browser, mouse, or AI call is made.
The fallback planner returns a single ``screen.capture`` step that writes
a file under ``settings.screenshots_dir``. We assert:

1. POST /task/plan returns a Plan with at least one step.
2. POST /task/run accepts the plan and returns a run_id.
3. A screenshot file exists under ``settings.screenshots_dir`` after the run.
4. A ``TASK_COMPLETED`` event was published on the event bus.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from automation_service.config import settings
from automation_service.engine.event_bus import event_bus


MVP_GOAL = (
    "Open Chrome, go to Google, search for AI automation, "
    "take a screenshot, save to Desktop, notify when finished"
)


@pytest.mark.slow
def test_mvp_plan_and_run(
    client,
    tmp_screenshots_dir: Path,
    tmp_workflows_dir: Path,
) -> None:
    """End-to-end: plan + run the MVP goal entirely in mock mode."""

    # ------------------------------------------------------------------
    # Step 1: capture TASK_COMPLETED events via the event bus. The bus's
    # sync handlers run in the publisher's thread, so a plain list works.
    # ------------------------------------------------------------------
    events: list[dict] = []
    event_bus.on("TASK_COMPLETED", lambda p: events.append(p))
    event_bus.on("TASK_FAILED", lambda p: events.append({"_failed": True, **p}))

    # ------------------------------------------------------------------
    # Step 2: ask the planner for a plan
    # ------------------------------------------------------------------
    r = client.post("/task/plan", params={"goal": MVP_GOAL})
    assert r.status_code == 200, f"plan failed: {r.status_code} {r.text}"
    plan = r.json()
    assert plan["goal"] == MVP_GOAL
    assert isinstance(plan["steps"], list) and len(plan["steps"]) >= 1

    # The fallback planner returns a single screen.capture step. We accept
    # any plan whose overall_risk is low/medium (the planner never marks a
    # goal like this as HIGH/CRITICAL in fallback mode).
    assert plan["overall_risk"] in {"low", "medium"}
    # Every step must declare a tool name.
    assert all(s.get("action") for s in plan["steps"])

    # ------------------------------------------------------------------
    # Step 3: execute the plan
    # ------------------------------------------------------------------
    r = client.post("/task/run", json=plan)
    assert r.status_code == 200, f"run failed: {r.status_code} {r.text}"
    run_body = r.json()
    assert "run_id" in run_body
    assert run_body["plan_id"] == plan["id"]

    # ------------------------------------------------------------------
    # Step 4: give the executor a tiny grace period (the executor is async
    # but TestClient awaits it). Poll the screenshots_dir for a few seconds.
    # ------------------------------------------------------------------
    deadline = time.time() + 5.0
    screenshot_files: list[Path] = []
    while time.time() < deadline:
        screenshot_files = list(tmp_screenshots_dir.glob("*.png"))
        if screenshot_files:
            break
        time.sleep(0.1)

    assert screenshot_files, (
        f"no screenshot file was created under {tmp_screenshots_dir}"
    )
    # The file must be non-empty (mock mode writes a placeholder PNG header
    # or a 1x1 image via PIL).
    first = screenshot_files[0]
    assert first.stat().st_size > 0

    # ------------------------------------------------------------------
    # Step 5: assert a TASK_COMPLETED event was emitted
    # ------------------------------------------------------------------
    # The executor publishes events synchronously from within the same
    # async context that TestClient runs; the sync handler list should
    # already contain the event.
    assert any("_failed" not in e for e in events), (
        f"expected TASK_COMPLETED event but got: {events}"
    )
    completed = [e for e in events if "_failed" not in e]
    assert len(completed) >= 1
    # The payload should reference the run_id we just got back.
    assert any(e.get("run_id") == run_body["run_id"] for e in completed), (
        f"TASK_COMPLETED payload missing run_id; got: {completed}"
    )


@pytest.mark.slow
def test_mvp_kill_switch_aborts_run(
    client,
    tmp_screenshots_dir: Path,
) -> None:
    """If the kill switch is engaged before /task/run, the run is rejected."""
    client.post("/emergency-stop")
    r = client.post(
        "/task/plan",
        params={"goal": "Open Chrome and search for AI automation"},
    )
    assert r.status_code == 409


def test_mvp_screenshot_endpoint_also_writes_file(
    client,
    tmp_screenshots_dir: Path,
) -> None:
    """The /automation/screenshot endpoint is the smallest unit of the MVP
    pipeline — verify it produces a file under screenshots_dir."""
    before = set(tmp_screenshots_dir.glob("*.png"))
    r = client.post("/automation/screenshot")
    assert r.status_code == 200
    after = set(tmp_screenshots_dir.glob("*.png"))
    new_files = after - before
    assert new_files, "no new screenshot file was written"
    f = new_files.pop()
    assert f.stat().st_size > 0

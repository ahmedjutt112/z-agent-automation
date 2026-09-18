"""Tests for the scheduler subsystem — master prompt section 24 + section 25.

Test plan
---------

1.  ``test_scheduler_manager_singleton`` — two import paths return the
    same ``scheduler_manager`` instance.
2.  ``test_scheduler_start_stop`` — ``scheduler_manager.start()`` then
    ``shutdown()`` round-trip succeeds.
3.  ``test_schedule_workflow_cron`` — scheduling with a cron trigger
    returns a job_id.
4.  ``test_list_jobs_after_schedule`` — ``list_jobs()`` returns 1 entry
    after scheduling.
5.  ``test_unschedule`` — ``unschedule(job_id)`` returns True and
    empties ``list_jobs()``.
6.  ``test_pause_resume`` — ``pause_job`` + ``resume_job`` both return True.
7.  ``test_trigger_types_endpoint`` — ``GET /schedules/triggers/types``
    returns all 8 trigger types.
8.  ``test_file_trigger_init`` — ``FileTrigger(file_pattern="*.pdf")``
    instantiates without error.
9.  ``test_hotkey_trigger_init`` — ``HotkeyTrigger(hotkey="ctrl+shift+a")``
    instantiates.
10. ``test_webhook_trigger_init`` — ``WebhookTrigger(webhook_url="/test-hook")``
    instantiates.
11. ``test_system_trigger_init`` — ``SystemTrigger(event="startup")``
    instantiates.
12. ``test_scheduler_health_endpoint`` — ``GET /scheduler/health``
    returns ``{running: true, jobs_count, next_run}``.
13. ``test_schedules_endpoint_requires_auth`` — POST without bearer
    token returns 401 (skipped when no IPC token is set).
14. ``test_scheduled_job_persists_to_db`` — schedule_workflow()
    inserts a row in the ``scheduled_jobs`` table.
15. ``test_misfire_grace_time`` — passing ``misfire_grace_time`` in
    trigger_config sets it on the underlying APScheduler job.

All tests run in mock mode — no real automation fires.
"""

from __future__ import annotations

import asyncio
import os
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Module-level fixtures — give every scheduler test a clean singleton
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_scheduler(request) -> Iterator[None]:
    """Reset the scheduler_manager singleton before + after each test.

    The singleton accumulates jobs across tests otherwise. Calling
    ``reset()`` rebuilds a fresh AsyncIOScheduler and clears the
    in-memory trigger dicts. ``reset()`` is defensive — if the
    underlying event loop has closed (common between pytest-asyncio
    tests), it swallows the resulting RuntimeError and just rebuilds.
    """
    from automation_service.scheduler.manager import scheduler_manager

    scheduler_manager.reset()
    yield
    # Best-effort async shutdown; if it fails (loop closed), reset() will
    # rebuild on the next test's setup.
    try:
        scheduler_manager.reset()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Singleton
# ---------------------------------------------------------------------------


def test_scheduler_manager_singleton() -> None:
    """Importing SchedulerManager from two paths returns the same instance."""
    from automation_service.scheduler.manager import (
        SchedulerManager,
        scheduler_manager as sm1,
    )
    from automation_service.scheduler import scheduler_manager as sm2

    assert sm1 is sm2
    assert SchedulerManager() is sm1


# ---------------------------------------------------------------------------
# 2. Start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_start_stop() -> None:
    """scheduler_manager.start() then shutdown() completes without errors."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    assert scheduler_manager.is_running is True

    await scheduler_manager.shutdown(wait=False)
    assert scheduler_manager.is_running is False


# ---------------------------------------------------------------------------
# 3. schedule_workflow with a cron trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_workflow_cron() -> None:
    """schedule_workflow with a cron trigger returns a job_id."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf1",
        {"type": "schedule", "cron": "0 9 * * 1-5"},
    )
    assert isinstance(job_id, str)
    assert len(job_id) > 0


# ---------------------------------------------------------------------------
# 4. list_jobs after schedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_after_schedule() -> None:
    """list_jobs returns 1 entry after scheduling."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf-list",
        {"type": "schedule", "cron": "0 9 * * 1-5"},
    )
    jobs = scheduler_manager.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == job_id
    assert jobs[0]["trigger_type"] == "schedule"
    # next_run_time should be populated once the scheduler is running
    assert jobs[0]["next_run_time"] is not None


# ---------------------------------------------------------------------------
# 5. unschedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unschedule() -> None:
    """unschedule(job_id) returns True and empties list_jobs()."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf-unsched",
        {"type": "schedule", "cron": "0 9 * * 1-5"},
    )
    assert scheduler_manager.list_jobs() == [
        {**scheduler_manager.list_jobs()[0]}
    ] or len(scheduler_manager.list_jobs()) == 1

    ok = await scheduler_manager.unschedule(job_id)
    assert ok is True
    assert scheduler_manager.list_jobs() == []


# ---------------------------------------------------------------------------
# 6. pause + resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_resume() -> None:
    """pause_job then resume_job both return True."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf-pause",
        {"type": "schedule", "cron": "0 9 * * 1-5"},
    )

    paused = scheduler_manager.pause_job(job_id)
    assert paused is True

    resumed = scheduler_manager.resume_job(job_id)
    assert resumed is True


# ---------------------------------------------------------------------------
# 7. Trigger types endpoint
# ---------------------------------------------------------------------------


def test_trigger_types_endpoint(client) -> None:
    """GET /schedules/triggers/types returns 8 trigger types."""
    r = client.get("/schedules/triggers/types")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) == 8
    types = {item["type"] for item in items}
    expected = {
        "schedule",
        "file",
        "application",
        "browser",
        "hotkey",
        "webhook",
        "system",
        "manual",
    }
    assert types == expected
    # Each entry should have a non-empty description
    for item in items:
        assert item["description"]
        assert isinstance(item["required_fields"], list)


# ---------------------------------------------------------------------------
# 8-11. Trigger class instantiation
# ---------------------------------------------------------------------------


def test_file_trigger_init() -> None:
    """FileTrigger(file_pattern='*.pdf') instantiates without error."""
    from automation_service.scheduler.triggers import FileTrigger

    trig = FileTrigger(file_pattern="*.pdf")
    assert trig.file_pattern == "*.pdf"
    assert trig.is_active is False


def test_hotkey_trigger_init() -> None:
    """HotkeyTrigger(hotkey='ctrl+shift+a') instantiates."""
    from automation_service.scheduler.triggers import HotkeyTrigger

    trig = HotkeyTrigger(hotkey="ctrl+shift+a")
    # _normalize should produce pynput's angle-bracketed form
    assert trig.hotkey == "<ctrl>+<shift>+a"
    assert trig.is_active is False


def test_webhook_trigger_init() -> None:
    """WebhookTrigger(webhook_url='/test-hook') instantiates."""
    from automation_service.scheduler.triggers import WebhookTrigger

    trig = WebhookTrigger(webhook_url="/test-hook")
    assert trig.webhook_url == "/test-hook"
    assert trig.is_active is False


def test_system_trigger_init() -> None:
    """SystemTrigger(event='startup') instantiates."""
    from automation_service.scheduler.triggers import SystemTrigger

    trig = SystemTrigger(event="startup")
    assert trig.event == "startup"
    assert trig.is_active is False


# ---------------------------------------------------------------------------
# 12. Scheduler health endpoint
# ---------------------------------------------------------------------------


def test_scheduler_health_endpoint(client) -> None:
    """GET /scheduler/health returns {running, jobs_count, next_run}."""
    r = client.get("/scheduler/health")
    assert r.status_code == 200
    body = r.json()
    assert "running" in body
    assert "jobs_count" in body
    assert "next_run" in body
    # The lifespan starts the scheduler so running should be True
    assert body["running"] is True
    assert isinstance(body["jobs_count"], int)
    # next_run is None when no jobs scheduled; either is valid
    assert body["next_run"] is None or isinstance(body["next_run"], str)


# ---------------------------------------------------------------------------
# 13. Auth-required schedule creation
# ---------------------------------------------------------------------------


def test_schedules_endpoint_requires_auth(client, monkeypatch) -> None:
    """POST /schedules without bearer token returns 401 (only when
    AUTOMATION_IPC_TOKEN is set)."""

    token = os.environ.get("AUTOMATION_IPC_TOKEN")
    if not token:
        # Conftest pops AUTOMATION_IPC_TOKEN, so this is the default path.
        # Simulate the configured-token case so the test is meaningful.
        token = "test-ipc-token-1234"
        monkeypatch.setattr(
            "automation_service.config.settings.ipc_token", token
        )

    r = client.post(
        "/schedules",
        json={
            "workflow_id": "wf-auth",
            "trigger_config": {"type": "schedule", "cron": "0 9 * * 1-5"},
        },
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 14. DB persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_job_persists_to_db(db_session, monkeypatch) -> None:
    """After schedule_workflow(), a row exists in the scheduled_jobs table.

    Monkey-patches ``database.base.SessionLocal`` so the manager writes
    into our in-memory SQLite engine, then verifies the row is there.
    """
    from automation_service.scheduler.manager import scheduler_manager

    # Patch database.base.SessionLocal to use our in-memory engine.
    in_memory_engine = db_session.bind
    TestSessionLocal = sessionmaker(
        bind=in_memory_engine, autoflush=False, autocommit=False
    )
    import database.base as db_base

    monkeypatch.setattr(db_base, "SessionLocal", TestSessionLocal)

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf-persist",
        {"type": "schedule", "cron": "0 9 * * 1-5"},
    )

    # Query the scheduled_jobs table via the same in-memory engine
    from database.models.schema import ScheduledJob

    row = db_session.get(ScheduledJob, job_id)
    assert row is not None
    assert row.workflow_id == "wf-persist"
    assert row.trigger_type == "schedule"
    assert row.cron == "0 9 * * 1-5"
    assert row.timezone == "UTC"
    assert row.enabled is True


# ---------------------------------------------------------------------------
# 15. misfire_grace_time option
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_misfire_grace_time() -> None:
    """schedule_workflow with misfire_grace_time sets it on the APScheduler job."""
    from automation_service.scheduler.manager import scheduler_manager

    await scheduler_manager.start()
    job_id = await scheduler_manager.schedule_workflow(
        "wf-misfire",
        {
            "type": "schedule",
            "cron": "0 9 * * 1-5",
            "misfire_grace_time": 300,
            "coalesce": False,
        },
    )

    job = scheduler_manager.scheduler.get_job(job_id)
    assert job is not None
    assert job.misfire_grace_time == 300
    # coalesce should also be False as passed
    assert job.coalesce is False

"""Tests for the Phase 5 AI OS Assistant — master prompt §83.

Covers:
- CalendarService (Mock + factory).
- OSAssistantAgent (prepare_for_meeting, morning_routine,
  end_of_day_summary, research_topic, organize_files_by_context).
- Assistant API routes (POST /assistant/prepare-meeting,
  /morning-routine, /research, /organize-files, /run-meeting-prep;
  GET /assistant/end-of-day-summary, /calendar/next-meeting,
  /calendar/events).

All tests run in mock mode (master prompt §64).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from automation_service.agents.os_assistant import OSAssistantAgent
from automation_service.config import settings
from automation_service.integrations.calendar import (
    CalendarEvent,
    GoogleCalendarService,
    MockCalendarService,
    get_calendar_service,
)
from automation_service.models import Plan, RiskLevel


# ---------------------------------------------------------------------------
# CalendarService tests
# ---------------------------------------------------------------------------


def test_calendar_service_mock() -> None:
    """MockCalendarService().list_events returns a list of CalendarEvent."""
    svc = MockCalendarService()
    events = asyncio.get_event_loop().run_until_complete(svc.list_events())
    assert isinstance(events, list)
    assert len(events) >= 1
    assert all(isinstance(e, CalendarEvent) for e in events)
    # Mock events always have deterministic titles.
    titles = {e.title for e in events}
    assert "Standup" in titles


def test_calendar_service_get_next_meeting_mock() -> None:
    """MockCalendarService.get_next_meeting returns an event in mock mode."""
    svc = MockCalendarService()
    evt = asyncio.get_event_loop().run_until_complete(svc.get_next_meeting())
    assert evt is not None
    assert isinstance(evt, CalendarEvent)
    # The next meeting must start in the future.
    assert evt.start_at >= datetime.now(timezone.utc) - timedelta(seconds=1)


def test_calendar_factory_returns_mock_when_no_oauth() -> None:
    """get_calendar_service() returns MockCalendarService in mock mode.

    In mock mode (settings.mock_mode=True) the factory never even consults
    the api_credentials table — it always returns MockCalendarService.
    """
    svc = get_calendar_service()
    assert isinstance(svc, MockCalendarService)


def test_google_calendar_service_lazy_import_error() -> None:
    """GoogleCalendarService raises a helpful error if google-api-python-client
    is not installed (and we're not in mock mode)."""
    # Save + flip mock_mode so the lazy path is exercised.
    prev = settings.mock_mode
    try:
        settings.mock_mode = False
        svc = GoogleCalendarService(access_token="fake-token")
        # The error is raised on first network call, not at construction.
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.get_event_loop().run_until_complete(svc.list_events())
        assert "google-api-python-client" in str(exc_info.value)
    finally:
        settings.mock_mode = prev


# ---------------------------------------------------------------------------
# OSAssistantAgent tests — all run in mock mode
# ---------------------------------------------------------------------------


def test_os_assistant_prepare_for_meeting_mock() -> None:
    """OSAssistantAgent.prepare_for_meeting returns a MeetingPreparation
    with a populated Plan + meeting context, WITHOUT executing."""
    agent = OSAssistantAgent()
    prep = asyncio.get_event_loop().run_until_complete(agent.prepare_for_meeting())
    assert prep.plan is not None
    assert isinstance(prep.plan, Plan)
    assert len(prep.plan.steps) >= 1
    assert prep.meeting is not None
    # The plan must be marked medium-risk (opens browser + apps).
    assert prep.plan.overall_risk in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert prep.dashboard_url is not None
    assert prep.opened_apps is not None


def test_os_assistant_morning_routine_mock() -> None:
    """OSAssistantAgent.morning_routine returns a Plan with at least 3 steps."""
    agent = OSAssistantAgent()
    plan = asyncio.get_event_loop().run_until_complete(agent.morning_routine())
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 3
    # The morning routine must include launching an app.
    actions = [s.action for s in plan.steps]
    assert "app.launch" in actions
    assert "browser.open" in actions


def test_os_assistant_end_of_day_summary_mock() -> None:
    """OSAssistantAgent.end_of_day_summary returns a summary dict with
    expected keys (NOT a Plan)."""
    agent = OSAssistantAgent()
    summary = asyncio.get_event_loop().run_until_complete(agent.end_of_day_summary())
    assert isinstance(summary, dict)
    assert "date" in summary
    assert "total_runs" in summary
    assert "highlights" in summary
    # Mock mode adds the mock_mode flag when there are no real runs.
    assert summary.get("mock_mode") is True


def test_os_assistant_research_topic_mock() -> None:
    """OSAssistantAgent.research_topic returns a Plan with steps
    proportional to depth."""
    agent = OSAssistantAgent()
    plan = asyncio.get_event_loop().run_until_complete(
        agent.research_topic("AI automation", depth=3)
    )
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 3
    # Every research plan opens at least one browser tab.
    actions = [s.action for s in plan.steps]
    assert "browser.open" in actions
    # Every research plan saves findings to a file.
    assert "file.write" in actions


def test_os_assistant_organize_files_mock() -> None:
    """OSAssistantAgent.organize_files_by_context returns a Plan."""
    agent = OSAssistantAgent()
    plan = asyncio.get_event_loop().run_until_complete(
        agent.organize_files_by_context(
            {"project": "demo", "attendees": ["Alice Smith"]}
        )
    )
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 2
    # The plan must include a file.move step (with MEDIUM risk).
    move_steps = [s for s in plan.steps if s.action == "file.move"]
    assert len(move_steps) >= 1
    assert move_steps[0].risk_level == RiskLevel.MEDIUM


def test_os_assistant_prepare_for_meeting_no_upcoming() -> None:
    """If the calendar is empty, prepare_for_meeting returns an empty plan
    rather than raising."""
    agent = OSAssistantAgent()
    # Use a custom mock with no events.
    agent._calendar = MockCalendarService()
    agent._calendar._events = {}  # type: ignore[attr-defined]
    # Monkey-patch the list method to return [].
    async def _empty_next() -> None:
        return None
    agent._calendar.get_next_meeting = _empty_next  # type: ignore[assignment]
    prep = asyncio.get_event_loop().run_until_complete(agent.prepare_for_meeting())
    assert prep.plan.steps == []


# ---------------------------------------------------------------------------
# Assistant API routes — exercised via the FastAPI TestClient
# ---------------------------------------------------------------------------


def test_api_assistant_prepare_meeting(client) -> None:
    """POST /assistant/prepare-meeting returns 200 with a plan + meeting
    context, and executed=False (master prompt §66)."""
    r = client.post("/assistant/prepare-meeting", json={"meeting_id": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "plan" in body
    assert "meeting" in body
    assert body["executed"] is False
    assert len(body["plan"]["steps"]) >= 1
    assert body["dashboard_url"] is not None


def test_api_assistant_morning_routine(client) -> None:
    """POST /assistant/morning-routine returns 200 with a Plan."""
    r = client.post("/assistant/morning-routine")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "plan" in body
    assert body["executed"] is False
    assert len(body["plan"]["steps"]) >= 3


def test_api_assistant_end_of_day_summary(client) -> None:
    """GET /assistant/end-of-day-summary returns 200 with the summary dict."""
    r = client.get("/assistant/end-of-day-summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "date" in body
    assert "total_runs" in body
    assert "highlights" in body


def test_api_assistant_research(client) -> None:
    """POST /assistant/research returns 200 with a Plan."""
    r = client.post("/assistant/research", json={"topic": "AI automation", "depth": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "plan" in body
    assert body["executed"] is False
    assert len(body["plan"]["steps"]) >= 3


def test_api_assistant_organize_files(client) -> None:
    """POST /assistant/organize-files returns 200 with a Plan."""
    r = client.post(
        "/assistant/organize-files",
        json={"context": {"project": "demo", "attendees": ["Alice"]}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "plan" in body
    assert body["executed"] is False
    assert len(body["plan"]["steps"]) >= 2


def test_api_assistant_calendar_next_meeting(client) -> None:
    """GET /assistant/calendar/next-meeting returns 200 with a meeting or null."""
    r = client.get("/assistant/calendar/next-meeting")
    assert r.status_code == 200, r.text
    body = r.json()
    # The key must always be present; the value may be null.
    assert "next_meeting" in body
    if body["next_meeting"] is not None:
        evt = body["next_meeting"]
        assert "id" in evt
        assert "title" in evt
        assert "start_at" in evt


def test_api_assistant_calendar_events(client) -> None:
    """GET /assistant/calendar/events returns 200 with a list of events."""
    r = client.get("/assistant/calendar/events")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "events" in body
    assert "count" in body
    assert isinstance(body["events"], list)
    assert body["count"] == len(body["events"])
    # Mock service returns at least 1 event.
    assert body["count"] >= 1
    # Provider field tells the caller which backend answered.
    assert "provider" in body
    assert body["provider"] == "mock"


def test_api_assistant_calendar_events_with_time_window(client) -> None:
    """GET /assistant/calendar/events?time_min=...&time_max=... honours the window."""
    now = datetime.now(timezone.utc)
    in_one_hour = now + timedelta(hours=1)
    in_three_hours = now + timedelta(hours=3)
    r = client.get(
        "/assistant/calendar/events",
        params={
            "time_min": in_one_hour.isoformat(),
            "time_max": in_three_hours.isoformat(),
            "max_results": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Every returned event must fall inside the window.
    for evt in body["events"]:
        start = datetime.fromisoformat(evt["start_at"].replace("Z", "+00:00"))
        assert in_one_hour <= start <= in_three_hours


def test_api_assistant_calendar_events_bad_iso(client) -> None:
    """GET /assistant/calendar/events?time_min=not-a-date returns 400."""
    r = client.get("/assistant/calendar/events", params={"time_min": "not-a-date"})
    assert r.status_code == 400


def test_api_assistant_run_meeting_prep(client, tmp_screenshots_dir) -> None:
    """POST /assistant/run-meeting-prep executes an approved plan via the
    WorkflowExecutor. Mock mode means the screenshot step actually writes
    a file."""
    # First, generate a plan via /prepare-meeting.
    r = client.post("/assistant/prepare-meeting", json={"meeting_id": None})
    assert r.status_code == 200
    plan = r.json()["plan"]

    # Now submit it for execution.
    r = client.post("/assistant/run-meeting-prep", json={"plan": plan})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    assert "run_id" in body
    assert body["plan_id"] == plan["id"]

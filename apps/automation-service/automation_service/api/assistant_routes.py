"""FastAPI router for the Phase 5 AI OS Assistant — master prompt §83.

Mounted under ``/assistant`` in main.py. All routes require the IPC bearer
token (resolved lazily from ``automation_service.main`` to avoid a circular
import).

Endpoints
---------

Assistant:
- ``POST /assistant/prepare-meeting`` — body: {meeting_id?} — returns a
  :class:`MeetingPreparation` (plan + meeting context, NO execution).
- ``POST /assistant/run-meeting-prep`` — body: {plan} — executes the
  already-approved plan via the WorkflowExecutor. Defense in depth:
  the permission engine is re-evaluated before execution.
- ``POST /assistant/organize-files`` — body: {context} — returns a Plan.
- ``POST /assistant/morning-routine`` — returns a Plan.
- ``GET  /assistant/end-of-day-summary`` — returns a summary dict.
- ``POST /assistant/research`` — body: {topic, depth?} — returns a Plan.

Calendar (proxied through the configured CalendarService):
- ``GET /assistant/calendar/next-meeting`` — returns the next event or null.
- ``GET /assistant/calendar/events`` — query: time_min, time_max — list.

CRITICAL (master prompt §83): every external action must still pass through
permissions and user-defined policies. The ``prepare-meeting`` /
``organize-files`` / ``morning-routine`` / ``research`` endpoints return
Plans WITHOUT executing them — the frontend must display each Plan and
require explicit user approval before calling ``run-meeting-prep`` or
``/task/run``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..agents.os_assistant import OSAssistantAgent, os_assistant
from ..config import settings
from ..engine.workflow_executor import WorkflowExecutor
from ..integrations.calendar import (
    CalendarAttendee,
    CalendarEvent,
    get_calendar_service,
)
from ..models import Plan


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import to avoid circular with automation_service.main
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` lazily from main.

    Keeps this router import-safe even before the FastAPI app is built.
    """
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------


class PrepareMeetingRequest(BaseModel):
    meeting_id: Optional[str] = Field(
        None,
        description="Optional meeting id. If omitted, the next upcoming "
        "meeting is used.",
    )


class RunPlanRequest(BaseModel):
    """Body for POST /assistant/run-meeting-prep — execute an approved plan."""

    plan: Plan


class OrganizeFilesRequest(BaseModel):
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context dict — may include 'project', 'date_range' "
        "({'start','end'}), 'attendees' (list[str]), and 'destination'.",
    )


class ResearchRequest(BaseModel):
    topic: str = Field(..., description="Topic to research.")
    depth: int = Field(
        3,
        ge=1,
        le=5,
        description="Research depth (1-5). Controls how many tabs / queries.",
    )


# ---------------------------------------------------------------------------
# Assistant routes — every plan-returning route is NON-executing (§66)
# ---------------------------------------------------------------------------


@router.post(
    "/prepare-meeting",
    dependencies=[Depends(_verify_ipc_token)],
)
async def prepare_meeting(req: PrepareMeetingRequest) -> dict:
    """Generate a meeting-prep Plan WITHOUT executing it.

    Returns the Plan + meeting context. The caller (renderer / voice
    pipeline) must display the Plan and require explicit user approval
    before calling /assistant/run-meeting-prep or /task/run.
    """
    agent = OSAssistantAgent()
    try:
        prep = await agent.prepare_for_meeting(meeting_id=req.meeting_id)
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"meeting not found: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"calendar lookup failed: {exc}",
        )

    return {
        "plan": prep.plan.model_dump(mode="json"),
        "meeting": prep.meeting.model_dump(mode="json"),
        "opened_apps": prep.opened_apps,
        "opened_tabs": prep.opened_tabs,
        "organized_files": prep.organized_files,
        "dashboard_url": prep.dashboard_url,
        "executed": False,  # master prompt §83 — never auto-execute
    }


@router.post(
    "/run-meeting-prep",
    dependencies=[Depends(_verify_ipc_token)],
)
async def run_meeting_prep(req: RunPlanRequest) -> dict:
    """Execute an already-approved meeting-prep Plan.

    Defense in depth: the WorkflowExecutor consults the permission engine
    on every step before executing it (§10). If any step is denied, the
    run aborts and the denied step is reported in the response.
    """
    executor = WorkflowExecutor()
    run_id = await executor.execute_plan(req.plan)
    return {
        "run_id": run_id,
        "plan_id": str(req.plan.id),
        "status": "running",
        "executed": True,
    }


@router.post(
    "/organize-files",
    dependencies=[Depends(_verify_ipc_token)],
)
async def organize_files(req: OrganizeFilesRequest) -> dict:
    """Return a file-organisation Plan WITHOUT executing it."""
    agent = OSAssistantAgent()
    plan = await agent.organize_files_by_context(req.context)
    return {"plan": plan.model_dump(mode="json"), "executed": False}


@router.post(
    "/morning-routine",
    dependencies=[Depends(_verify_ipc_token)],
)
async def morning_routine() -> dict:
    """Return a morning-routine Plan WITHOUT executing it."""
    agent = OSAssistantAgent()
    plan = await agent.morning_routine()
    return {"plan": plan.model_dump(mode="json"), "executed": False}


@router.get(
    "/end-of-day-summary",
    dependencies=[Depends(_verify_ipc_token)],
)
async def end_of_day_summary() -> dict:
    """Return a summary of today's automation activities (no plan)."""
    agent = OSAssistantAgent()
    summary = await agent.end_of_day_summary()
    return summary


@router.post(
    "/research",
    dependencies=[Depends(_verify_ipc_token)],
)
async def research(req: ResearchRequest) -> dict:
    """Return a research Plan WITHOUT executing it."""
    agent = OSAssistantAgent()
    plan = await agent.research_topic(req.topic, depth=req.depth)
    return {"plan": plan.model_dump(mode="json"), "executed": False}


# ---------------------------------------------------------------------------
# Calendar routes — read-only proxies through the configured CalendarService
# ---------------------------------------------------------------------------


@router.get(
    "/calendar/next-meeting",
    dependencies=[Depends(_verify_ipc_token)],
)
async def calendar_next_meeting() -> dict:
    """Return the next upcoming CalendarEvent or {next_meeting: null}."""
    svc = get_calendar_service()
    try:
        evt = await svc.get_next_meeting()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"calendar lookup failed: {exc}",
        )
    if evt is None:
        return {"next_meeting": None}
    return {"next_meeting": evt.model_dump(mode="json")}


@router.get(
    "/calendar/events",
    dependencies=[Depends(_verify_ipc_token)],
)
async def calendar_events(
    time_min: Optional[str] = Query(None, description="ISO datetime"),
    time_max: Optional[str] = Query(None, description="ISO datetime"),
    max_results: int = Query(10, ge=1, le=100),
) -> dict:
    """List calendar events in the [time_min, time_max] window."""
    svc = get_calendar_service()
    tmin = _parse_dt(time_min)
    tmax = _parse_dt(time_max)
    try:
        events = await svc.list_events(tmin, tmax, max_results)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"calendar list failed: {exc}",
        )
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "count": len(events),
        "provider": svc.provider_name,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept "Z" suffix as +00:00
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid ISO datetime: {s!r}",
        )

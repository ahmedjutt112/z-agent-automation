"""FastAPI router for the scheduler subsystem.

Master prompt section 24 — Schedules endpoints.

Mounted under ``/schedules`` in main.py. All routes require the IPC
bearer token (resolved lazily from ``automation_service.main`` to avoid
the circular import).

Endpoints
---------

* ``GET    /schedules``                — list all scheduled jobs
* ``POST   /schedules``                 — schedule a workflow (body:
  ``{workflow_id, trigger_config}``); returns ``{job_id}``
* ``DELETE /schedules/{job_id}``        — unschedule
* ``POST   /schedules/{job_id}/pause``  — pause a job
* ``POST   /schedules/{job_id}/resume`` — resume a job
* ``GET    /schedules/triggers/types``  — list supported trigger types
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..models import TriggerType
from .manager import scheduler_manager


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency (lazy to avoid circular import with automation_service.main)
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` lazily so we don't create a circular import.

    The actual implementation lives in :mod:`automation_service.main`. We
    look it up at request-time to avoid importing ``main`` at module load
    (which would pull in the FastAPI app before all subsystems register).
    """
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ScheduleRequest(BaseModel):
    """Body of ``POST /schedules``."""

    workflow_id: str = Field(..., description="Workflow to fire")
    trigger_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Trigger configuration. Must include 'type' (one of "
            "TriggerType values). For SCHEDULE: also 'schedule_type' "
            "and 'cron' (or 'run_date' for once)."
        ),
    )


class ScheduleResponse(BaseModel):
    job_id: str


class JobDict(BaseModel):
    job_id: str
    workflow_id: str | None = None
    trigger_type: str
    next_run_time: str | None = None
    is_active: bool | None = None
    source: str | None = None


class TriggerTypeInfo(BaseModel):
    """One row in ``GET /schedules/triggers/types``."""

    type: str
    description: str
    required_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Trigger type catalog
# ---------------------------------------------------------------------------


_TRIGGER_TYPE_DESCRIPTIONS: dict[str, tuple[str, list[str]]] = {
    TriggerType.SCHEDULE.value: (
        "Time-based schedule (cron expression, hourly, daily, weekly, "
        "monthly, or one-shot run_date).",
        ["type", "schedule_type", "cron"],
    ),
    TriggerType.FILE.value: (
        "Fires when a file matching file_pattern is created / modified / "
        "deleted / moved in the watched directory.",
        ["type", "file_pattern"],
    ),
    TriggerType.APPLICATION.value: (
        "Fires when an application launches or closes. (Placeholder in "
        "this iteration — the engine polls for app state.)",
        ["type", "app_name"],
    ),
    TriggerType.BROWSER.value: (
        "Fires on a browser navigation event. (Placeholder — the engine "
        "polls browser sessions.)",
        ["type", "url_pattern"],
    ),
    TriggerType.HOTKEY.value: (
        "Fires when a global keyboard shortcut is pressed (ctrl+shift+a, "
        "etc.). Requires a running display server.",
        ["type", "hotkey"],
    ),
    TriggerType.WEBHOOK.value: (
        "Registers a POST endpoint under /webhooks/{token}; fires the "
        "workflow with the POST body as workflow variables.",
        ["type", "webhook_url"],
    ),
    TriggerType.SYSTEM.value: (
        "Fires on OS events: startup, login, idle (no input for N sec), "
        "or network_available.",
        ["type", "event"],
    ),
    TriggerType.MANUAL.value: (
        "No automatic trigger — the user invokes the workflow manually "
        "via POST /task/run.",
        ["type"],
    ),
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/triggers/types", dependencies=[Depends(_verify_ipc_token)])
async def list_trigger_types() -> list[dict[str, Any]]:
    """Return the 8 supported trigger types with descriptions."""
    out: list[dict[str, Any]] = []
    for trig_type in TriggerType:
        desc, required = _TRIGGER_TYPE_DESCRIPTIONS.get(
            trig_type.value, ("(no description)", [])
        )
        out.append(
            {
                "type": trig_type.value,
                "description": desc,
                "required_fields": list(required),
            }
        )
    return out


@router.get("", dependencies=[Depends(_verify_ipc_token)])
async def list_schedules() -> list[dict[str, Any]]:
    """List every scheduled job (APScheduler + standalone triggers)."""
    return scheduler_manager.list_jobs()


@router.post(
    "",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(req: ScheduleRequest) -> dict[str, str]:
    """Schedule a workflow. Returns ``{job_id}``."""
    if not req.workflow_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "workflow_id is required"
        )
    if not req.trigger_config.get("type"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "trigger_config.type is required (one of TriggerType values)",
        )
    try:
        job_id = await scheduler_manager.schedule_workflow(
            req.workflow_id, req.trigger_config
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"job_id": job_id}


@router.delete(
    "/{job_id}",
    dependencies=[Depends(_verify_ipc_token)],
)
async def delete_schedule(job_id: str) -> dict[str, Any]:
    """Unschedule a job. Returns ``{unscheduled: bool}``."""
    existed = await scheduler_manager.unschedule(job_id)
    if not existed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"job_id '{job_id}' not found"
        )
    return {"job_id": job_id, "unscheduled": True}


@router.post(
    "/{job_id}/pause",
    dependencies=[Depends(_verify_ipc_token)],
)
async def pause_schedule(job_id: str) -> dict[str, Any]:
    """Pause a scheduled job. Returns ``{paused: bool}``."""
    ok = scheduler_manager.pause_job(job_id)
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"job_id '{job_id}' not found"
        )
    return {"job_id": job_id, "paused": True}


@router.post(
    "/{job_id}/resume",
    dependencies=[Depends(_verify_ipc_token)],
)
async def resume_schedule(job_id: str) -> dict[str, Any]:
    """Resume a paused job. Returns ``{resumed: bool}``."""
    ok = scheduler_manager.resume_job(job_id)
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"job_id '{job_id}' not found"
        )
    return {"job_id": job_id, "resumed": True}

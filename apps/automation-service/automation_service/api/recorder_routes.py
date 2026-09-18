"""Task Recorder FastAPI router — master prompt §22 (Task Recorder) and
§35 (Recorder UI).

Mounted under ``/recorder`` in main.py. Endpoints:

* ``POST   /recorder/start``        — start a recording session
* ``POST   /recorder/pause``        — pause the active session
* ``POST   /recorder/resume``       — resume a paused session
* ``POST   /recorder/stop``         — stop + return the Recording
* ``GET    /recorder/status``       — current state dict
* ``GET    /recorder/events``       — current event list
* ``POST   /recorder/to-workflow``  — compile recording into a Workflow
* ``DELETE /recorder/events/{i}``    — drop one event by index before saving

All routes require the IPC bearer token (resolved lazily from
``automation_service.main`` to avoid the circular import).

In mock mode (``settings.mock_mode=True``) the recorder does NOT actually
hook into pynput / watchdog / Playwright — the underlying
:class:`automation_service.engine.recorder.TaskRecorder` emits a small
set of synthetic events when ``stop()`` is called so downstream tests
can exercise ``to_workflow()`` without a display server.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.recorder import (
    RecordedEvent,
    Recording,
    TaskRecorder,
    task_recorder,
)


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RecorderStatus(BaseModel):
    """Body of ``GET /recorder/status``."""

    recording: bool
    paused: bool
    events_count: int
    started_at: Optional[str] = None
    mock_mode: bool


class ToWorkflowRequest(BaseModel):
    """Body of ``POST /recorder/to-workflow``."""

    name: Optional[str] = Field(
        default=None,
        description="Optional name for the generated Workflow.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_dict(rec: TaskRecorder) -> dict[str, Any]:
    """Build the JSON-serialisable status dict the UI consumes."""
    started_at: Optional[str] = None
    if rec._recording is not None:  # noqa: SLF001 — we own this class
        started_at = rec._recording.started_at.isoformat()  # noqa: SLF001
    return {
        "recording": rec.is_recording,
        "paused": rec.state == "paused",
        "events_count": len(rec._recording.events) if rec._recording else 0,  # noqa: SLF001
        "started_at": started_at,
        "mock_mode": bool(settings.mock_mode),
    }


def _recording_or_404(rec: TaskRecorder) -> Recording:
    if rec._recording is None:  # noqa: SLF001
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no active recording — POST /recorder/start first",
        )
    return rec._recording  # noqa: SLF001


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_start() -> dict[str, Any]:
    """Start a fresh recording session.

    Idempotent: calling ``start()`` while already recording is a no-op
    (the underlying :class:`TaskRecorder` logs a warning and returns).
    """
    task_recorder.start()
    return _state_dict(task_recorder)


@router.post(
    "/pause",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_pause() -> dict[str, Any]:
    """Pause the active recording. No-op if not recording."""
    task_recorder.pause()
    return _state_dict(task_recorder)


@router.post(
    "/resume",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_resume() -> dict[str, Any]:
    """Resume a paused recording. No-op if not paused."""
    task_recorder.resume()
    return _state_dict(task_recorder)


@router.post(
    "/stop",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_stop() -> dict[str, Any]:
    """Stop the active recording and return the resulting Recording.

    Returns 409 when there's nothing to stop.
    """
    if task_recorder.state not in {"recording", "paused"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "not recording — POST /recorder/start first",
        )
    recording = task_recorder.stop()
    return {
        "recording": recording.model_dump(mode="json"),
        "status": task_recorder.state,
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/status",
    response_model=RecorderStatus,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_status() -> dict[str, Any]:
    """Return the current recorder state."""
    return _state_dict(task_recorder)


@router.get(
    "/events",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_events() -> dict[str, Any]:
    """Return the current event list (empty when no recording is active)."""
    rec = task_recorder._recording  # noqa: SLF001
    if rec is None:
        return {"events": [], "count": 0}
    return {
        "events": [e.model_dump(mode="json") for e in rec.events],
        "count": len(rec.events),
    }


@router.post(
    "/to-workflow",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_to_workflow(req: ToWorkflowRequest) -> dict[str, Any]:
    """Compile the current recording into a :class:`Workflow`.

    Returns 409 when there's no recording to compile.
    """
    rec = task_recorder._recording  # noqa: SLF001
    if rec is None or task_recorder.state == "idle":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no recording available — start + stop a recording first",
        )
    workflow = task_recorder.to_workflow(rec, name=req.name)
    return {
        "workflow": workflow.model_dump(mode="json"),
        "events_count": len(rec.events),
        "mock_mode": bool(settings.mock_mode),
    }


@router.delete(
    "/events/{index}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["recorder"],
)
async def recorder_delete_event(index: int) -> dict[str, Any]:
    """Delete one event by index from the active recording.

    Master prompt §35 — users can prune captured events (e.g. an
    accidental mouse click) before compiling the recording into a
    workflow.
    """
    rec = _recording_or_404(task_recorder)
    if index < 0 or index >= len(rec.events):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"event index {index} out of range (0..{len(rec.events) - 1})",
        )
    removed = rec.events.pop(index)
    return {
        "removed": removed.model_dump(mode="json"),
        "remaining": len(rec.events),
    }

"""Task history FastAPI router — master prompt §36 (Task History).

Mounted under ``/history`` in main.py. Endpoints:

* ``GET    /history/tasks``                       — list tasks w/ filters
* ``GET    /history/tasks/{task_id}``             — task detail (steps + logs)
* ``GET    /history/tasks/{task_id}/screenshots`` — screenshots for a task
* ``GET    /history/tasks/{task_id}/logs``        — logs for a task
* ``POST   /history/tasks/{task_id}/rerun``       — re-run a task
* ``GET    /history/export``                       — export filtered tasks as CSV

When the database isn't reachable (mock mode without a configured db file)
the endpoints return empty lists / 404 so the UI can render an empty state
without crashing. The route layer is the only place that knows about the
SQLAlchemy session — the underlying WorkflowExecutor uses an in-process
``_runs`` dict and never touches the DB.

All routes require the IPC bearer token.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Optional DB session — returns None when the DB is unavailable (mock mode)
# or the schema hasn't been initialised yet (tables missing).
# ---------------------------------------------------------------------------


def _open_session():
    """Return an open SQLAlchemy session or ``None`` if the DB is unavailable.

    In mock mode the configured ``db/custom.db`` may exist on disk without
    having had its schema initialised. Callers wrap each query in a
    try/except SQLAlchemyError so a missing table is treated as "no data"
    rather than crashing the route.
    """
    try:
        from database.base import SessionLocal
        from database.models import schema  # noqa: F401 (registers metadata)
    except Exception:
        return None
    try:
        return SessionLocal()
    except Exception:
        return None


def _safe_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/tasks",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_list_tasks(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> dict[str, Any]:
    """List tasks with filters + pagination."""
    session = _open_session()
    if session is None:
        return {
            "tasks": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "mock_mode": True,
        }
    try:
        from database.models.schema import Task

        q = session.query(Task)
        if status:
            q = q.filter(Task.status == status)
        if date_from:
            try:
                q = q.filter(Task.created_at >= datetime.fromisoformat(date_from))
            except ValueError:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"invalid date_from: {date_from!r}",
                )
        if date_to:
            try:
                q = q.filter(Task.created_at <= datetime.fromisoformat(date_to))
            except ValueError:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"invalid date_to: {date_to!r}",
                )
        if search:
            q = q.filter(Task.name.ilike(f"%{search}%"))

        total = q.count()
        rows = q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()

        tasks: list[dict[str, Any]] = []
        for r in rows:
            tasks.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "status": r.status,
                    "profile_id": r.profile_id,
                    "started_at": _safe_iso(r.started_at),
                    "finished_at": _safe_iso(r.finished_at),
                    "created_at": _safe_iso(r.created_at),
                }
            )
        return {
            "tasks": tasks,
            "count": total,
            "limit": limit,
            "offset": offset,
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        # Tables missing (schema not initialised) — return empty list.
        return {
            "tasks": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "mock_mode": True,
        }
    finally:
        session.close()


@router.get(
    "/tasks/{task_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_task_detail(task_id: str) -> dict[str, Any]:
    """Return a task with steps + logs."""
    session = _open_session()
    if session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"task '{task_id}' not found (database unavailable)",
        )
    try:
        from database.models.schema import Task, TaskLog, TaskStep

        task = session.query(Task).filter(Task.id == task_id).first()
        if task is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"task '{task_id}' not found",
            )
        steps = (
            session.query(TaskStep)
            .filter(TaskStep.task_id == task_id)
            .order_by(TaskStep.started_at.asc())
            .all()
        )
        logs = (
            session.query(TaskLog)
            .filter(TaskLog.task_id == task_id)
            .order_by(TaskLog.timestamp.asc())
            .all()
        )
        return {
            "task": {
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "profile_id": task.profile_id,
                "plan_json": task.plan_json,
                "result_json": task.result_json,
                "started_at": _safe_iso(task.started_at),
                "finished_at": _safe_iso(task.finished_at),
                "created_at": _safe_iso(task.created_at),
            },
            "steps": [
                {
                    "id": s.id,
                    "step_id": s.step_id,
                    "tool_name": s.tool_name,
                    "status": s.status,
                    "risk_level": s.risk_level,
                    "confidence": s.confidence,
                    "args_json": s.args_json,
                    "output": s.output,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                    "started_at": _safe_iso(s.started_at),
                    "finished_at": _safe_iso(s.finished_at),
                }
                for s in steps
            ],
            "logs": [
                {
                    "id": log.id,
                    "timestamp": _safe_iso(log.timestamp),
                    "level": log.level,
                    "tool": log.tool,
                    "target": log.target,
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "payload": log.payload,
                }
                for log in logs
            ],
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        # Tables missing — treat as not found.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"task '{task_id}' not found (schema not initialised)",
        )
    finally:
        session.close()


@router.get(
    "/tasks/{task_id}/screenshots",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_task_screenshots(task_id: str) -> dict[str, Any]:
    """Return screenshots captured during a task."""
    session = _open_session()
    if session is None:
        return {"screenshots": [], "count": 0, "mock_mode": True}
    try:
        from database.models.schema import Screenshot

        rows = (
            session.query(Screenshot)
            .filter(Screenshot.task_id == task_id)
            .order_by(Screenshot.created_at.desc())
            .all()
        )
        out = [
            {
                "id": r.id,
                "file_path": r.file_path,
                "width": r.width,
                "height": r.height,
                "metadata_json": r.metadata_json or {},
                "created_at": _safe_iso(r.created_at),
            }
            for r in rows
        ]
        return {
            "screenshots": out,
            "count": len(out),
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        return {"screenshots": [], "count": 0, "mock_mode": True}
    finally:
        session.close()


@router.get(
    "/tasks/{task_id}/logs",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_task_logs(task_id: str) -> dict[str, Any]:
    """Return structured logs filtered to a single task."""
    session = _open_session()
    if session is None:
        return {"logs": [], "count": 0, "mock_mode": True}
    try:
        from database.models.schema import TaskLog

        rows = (
            session.query(TaskLog)
            .filter(TaskLog.task_id == task_id)
            .order_by(TaskLog.timestamp.asc())
            .all()
        )
        out = [
            {
                "id": log.id,
                "timestamp": _safe_iso(log.timestamp),
                "level": log.level,
                "tool": log.tool,
                "target": log.target,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "payload": log.payload,
            }
            for log in rows
        ]
        return {
            "logs": out,
            "count": len(out),
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        return {"logs": [], "count": 0, "mock_mode": True}
    finally:
        session.close()


class RerunResponse(BaseModel):
    task_id: str
    new_run_id: Optional[str] = None
    started: bool
    mock_mode: bool


@router.post(
    "/tasks/{task_id}/rerun",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_task_rerun(task_id: str) -> dict[str, Any]:
    """Re-run a task by re-executing its saved Plan.

    The Plan is loaded from ``tasks.plan_json``; if it's missing or the
    task doesn't exist the route returns 404. In mock mode (no DB), the
    route returns 404 since there's no plan to re-run.
    """
    session = _open_session()
    if session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"task '{task_id}' not found (database unavailable)",
        )
    try:
        from database.models.schema import Task

        task = session.query(Task).filter(Task.id == task_id).first()
        if task is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"task '{task_id}' not found",
            )
        plan_json = task.plan_json
        if not plan_json:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"task '{task_id}' has no saved plan to re-run",
            )

        # Re-instantiate the Plan and re-execute it.
        from ..models import Plan
        from ..engine.workflow_executor import WorkflowExecutor

        try:
            plan = Plan.model_validate(plan_json)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"failed to load saved plan: {exc}",
            )

        executor = WorkflowExecutor()
        new_run_id = await executor.execute_plan(plan)
        return {
            "task_id": task_id,
            "new_run_id": new_run_id,
            "started": True,
            "mock_mode": bool(settings.mock_mode),
        }
    except SQLAlchemyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"task '{task_id}' not found (schema not initialised)",
        )
    finally:
        session.close()


@router.get(
    "/export",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["history"],
)
async def history_export(
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Export filtered tasks as a CSV file."""
    session = _open_session()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "name",
            "status",
            "profile_id",
            "started_at",
            "finished_at",
            "created_at",
        ]
    )
    if session is not None:
        try:
            from database.models.schema import Task

            q = session.query(Task)
            if status_filter:
                q = q.filter(Task.status == status_filter)
            if date_from:
                try:
                    q = q.filter(Task.created_at >= datetime.fromisoformat(date_from))
                except ValueError:
                    pass
            if date_to:
                try:
                    q = q.filter(Task.created_at <= datetime.fromisoformat(date_to))
                except ValueError:
                    pass
            if search:
                q = q.filter(Task.name.ilike(f"%{search}%"))
            for r in q.order_by(Task.created_at.desc()).limit(10_000).all():
                writer.writerow(
                    [
                        r.id,
                        r.name,
                        r.status,
                        r.profile_id or "",
                        _safe_iso(r.started_at) or "",
                        _safe_iso(r.finished_at) or "",
                        _safe_iso(r.created_at) or "",
                    ]
                )
        except SQLAlchemyError:
            # Tables missing — the CSV will still contain the header row.
            pass
        finally:
            session.close()

    content = buf.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tasks.csv"},
    )

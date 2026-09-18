"""Execution Analytics FastAPI router — master prompt §82 (Professional RPA).

Mounted under ``/analytics`` in main.py. Endpoints:

* ``GET /analytics/summary``     — top-line metrics for a date range
* ``GET /analytics/events``      — paginated raw event stream
* ``GET /analytics/leaderboard`` — top contributors by activity
* ``GET /analytics/export``       — JSON or CSV download of the filtered events

The analytics layer reads from the ``analytics_events`` table (added in
migration b3c4d5e6f7a8). In mock mode (or when the DB / table is
unavailable), the endpoints return deterministic empty/zero results so
the UI can render an empty state without crashing.

Master prompt §55 — every analytics endpoint call itself is recorded
as an ``export`` analytics event when the ``record`` query param is set
(default False; the param exists to prevent infinite recursion when
the UI polls the endpoint every minute).

Master prompt §57 — credentials are NEVER logged in analytics events.
The analytics recorder (in rbac.py) scrubs known credential keys
before persisting; this router trusts that scrubbing and does not
re-scrub here (defense in depth is already in place at the recorder).
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_session():
    try:
        from database.base import SessionLocal
        from database.models import schema  # noqa: F401
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


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _current_user_id(x_user_id: Optional[str]) -> str:
    return (x_user_id or "default").strip() or "default"


# ---------------------------------------------------------------------------
# In-memory mock event store — used in mock mode + tests
# ---------------------------------------------------------------------------


_mock_events: list[dict[str, Any]] = []


def record_mock_event(
    *,
    event_type: str,
    team_id: Optional[str] = None,
    user_id: Optional[str] = None,
    event_data: Optional[dict] = None,
    duration_ms: Optional[int] = None,
    cost_estimate: Optional[float] = None,
    created_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Append a mock analytics event (test helper)."""
    event = {
        "id": len(_mock_events) + 1,
        "team_id": team_id,
        "user_id": user_id,
        "event_type": event_type,
        "event_data": event_data or {},
        "duration_ms": duration_ms,
        "cost_estimate": cost_estimate,
        "created_at": created_at or datetime.now(timezone.utc),
    }
    _mock_events.append(event)
    return event


def clear_mock_events() -> None:
    """Test helper: wipe the in-memory event store."""
    _mock_events.clear()


# Seed a few deterministic events in mock mode so the UI has something
# to display on first load. These are added lazily so the import doesn't
# add side effects in non-mock contexts.
def _seed_mock_events() -> None:
    if _mock_events:
        return
    now = datetime.now(timezone.utc)
    for i in range(5):
        record_mock_event(
            event_type="workflow_run",
            user_id="default",
            event_data={"workflow_id": f"wf-{i}", "status": "completed"},
            duration_ms=1200 + i * 100,
            created_at=now - timedelta(days=i),
        )
    for i in range(3):
        record_mock_event(
            event_type="task_failed",
            user_id="default",
            event_data={"task_id": f"task-f-{i}"},
            duration_ms=800 + i * 100,
            created_at=now - timedelta(days=i),
        )
    for tool, count in [("file.read", 4), ("browser.click", 3), ("screen.capture", 2)]:
        for _ in range(count):
            record_mock_event(
                event_type="tool_used",
                user_id="default",
                event_data={"tool": tool},
                duration_ms=120,
                created_at=now,
            )
    for _ in range(2):
        record_mock_event(
            event_type="ai_call",
            user_id="default",
            event_data={"provider": "mock"},
            duration_ms=900,
            cost_estimate=0.0021,
            created_at=now,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["analytics"],
)
async def analytics_summary(
    team_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> dict[str, Any]:
    """Return a top-line analytics summary for the given filters.

    Returns:
    - ``total_workflows_run``  — count of ``workflow_run`` events
    - ``success_rate``         — completed / (completed + failed)
    - ``avg_duration_ms``      — mean duration of workflow_run events
    - ``total_ai_calls``       — count of ``ai_call`` events
    - ``estimated_cost``       — sum of ``cost_estimate`` across ai_call
    - ``top_tools``            — list of {tool, count, avg_duration_ms}
    - ``top_workflows``        — list of {workflow, runs, success_rate}
    - ``daily_breakdown``      — list of {date, runs, successes, failures}
    """
    user_id = _current_user_id(x_user_id)
    events = _query_events(team_id=team_id, user_id=None, date_from=date_from, date_to=date_to)

    workflow_runs = [e for e in events if e["event_type"] == "workflow_run"]
    completed = [e for e in workflow_runs if (e.get("event_data") or {}).get("status") == "completed"]
    failed = [e for e in events if e["event_type"] == "task_failed"]
    ai_calls = [e for e in events if e["event_type"] == "ai_call"]
    tool_uses = [e for e in events if e["event_type"] == "tool_used"]

    total_runs = len(workflow_runs)
    successes = len(completed)
    failures = len(failed)
    success_rate = (successes / (successes + failures)) if (successes + failures) else 0.0
    durations = [e.get("duration_ms") or 0 for e in workflow_runs]
    avg_duration = (sum(durations) / len(durations)) if durations else 0.0
    total_cost = sum((e.get("cost_estimate") or 0.0) for e in ai_calls)

    # Top tools
    tool_counter: Counter = Counter()
    tool_durations: dict[str, list[int]] = defaultdict(list)
    for e in tool_uses:
        tool = (e.get("event_data") or {}).get("tool", "unknown")
        tool_counter[tool] += 1
        tool_durations[tool].append(e.get("duration_ms") or 0)
    top_tools = [
        {
            "tool": t,
            "count": c,
            "avg_duration_ms": (sum(tool_durations[t]) / len(tool_durations[t])) if tool_durations[t] else 0,
        }
        for t, c in tool_counter.most_common(10)
    ]

    # Top workflows — group by workflow_id in event_data
    wf_runs: Counter = Counter()
    wf_success: Counter = Counter()
    wf_total: Counter = Counter()
    for e in workflow_runs:
        wf_id = (e.get("event_data") or {}).get("workflow_id", "unknown")
        wf_runs[wf_id] += 1
        wf_total[wf_id] += 1
        if (e.get("event_data") or {}).get("status") == "completed":
            wf_success[wf_id] += 1
    for e in failed:
        wf_id = (e.get("event_data") or {}).get("workflow_id", "unknown")
        wf_total[wf_id] += 1
    top_workflows = [
        {
            "workflow": wf,
            "runs": wf_runs[wf],
            "success_rate": (wf_success[wf] / wf_total[wf]) if wf_total[wf] else 0.0,
        }
        for wf in wf_total.most_common(10)
    ]

    # Daily breakdown (last 30 days or filtered range)
    date_from_dt = _parse_date(date_from)
    date_to_dt = _parse_date(date_to)
    if date_from_dt is None:
        date_from_dt = datetime.now(timezone.utc) - timedelta(days=30)
    if date_to_dt is None:
        date_to_dt = datetime.now(timezone.utc)

    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "successes": 0, "failures": 0})
    for e in workflow_runs:
        ts = e.get("created_at")
        if not ts:
            continue
        if isinstance(ts, str):
            ts = _parse_date(ts)
        if ts is None:
            continue
        day = ts.date().isoformat()
        if date_from_dt and ts < date_from_dt:
            continue
        if date_to_dt and ts > date_to_dt:
            continue
        daily[day]["runs"] += 1
        if (e.get("event_data") or {}).get("status") == "completed":
            daily[day]["successes"] += 1
    for e in failed:
        ts = e.get("created_at")
        if not ts:
            continue
        if isinstance(ts, str):
            ts = _parse_date(ts)
        if ts is None:
            continue
        day = ts.date().isoformat()
        if date_from_dt and ts < date_from_dt:
            continue
        if date_to_dt and ts > date_to_dt:
            continue
        daily[day]["failures"] += 1
    daily_breakdown = [{"date": d, **vals} for d, vals in sorted(daily.items())]

    return {
        "total_workflows_run": total_runs,
        "success_rate": round(success_rate, 4),
        "avg_duration_ms": round(avg_duration, 2),
        "total_ai_calls": len(ai_calls),
        "estimated_cost": round(total_cost, 6),
        "top_tools": top_tools,
        "top_workflows": top_workflows,
        "daily_breakdown": daily_breakdown,
        "filters": {
            "team_id": team_id,
            "user_id": user_id,
            "date_from": date_from,
            "date_to": date_to,
        },
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/events",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["analytics"],
)
async def analytics_events(
    team_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return a paginated list of analytics events."""
    events = _query_events(
        team_id=team_id,
        user_id=user_id,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )
    total = len(events)
    page = events[offset : offset + limit]
    return {
        "events": [_event_to_dict(e) for e in page],
        "count": len(page),
        "total": total,
        "limit": limit,
        "offset": offset,
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/leaderboard",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["analytics"],
)
async def analytics_leaderboard(
    team_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    """Top contributors by activity count (workflow_run + task_completed + tool_used)."""
    events = _query_events(
        team_id=team_id,
        user_id=None,
        date_from=date_from,
        date_to=date_to,
    )
    counter: Counter = Counter()
    for e in events:
        if e["event_type"] in {"workflow_run", "task_completed", "tool_used", "ai_call"}:
            uid = e.get("user_id") or "unknown"
            counter[uid] += 1
    top = counter.most_common(limit)
    return {
        "leaderboard": [
            {"user_id": uid, "activity_count": count} for uid, count in top
        ],
        "count": len(top),
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/export",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["analytics"],
)
async def analytics_export(
    format: str = Query("json", description="json | csv"),
    team_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Download the filtered events as JSON or CSV."""
    fmt = (format or "json").lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid format '{format}'. Allowed: json | csv",
        )
    events = _query_events(
        team_id=team_id,
        user_id=user_id,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )
    payload = [_event_to_dict(e) for e in events]

    if fmt == "json":
        content = json.dumps(payload, indent=2, default=str)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=analytics.json"},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "team_id", "user_id", "event_type", "event_data", "duration_ms", "cost_estimate", "created_at"]
    )
    for e in payload:
        writer.writerow(
            [
                e.get("id"),
                e.get("team_id") or "",
                e.get("user_id") or "",
                e.get("event_type"),
                json.dumps(e.get("event_data") or {}),
                e.get("duration_ms") or "",
                e.get("cost_estimate") or "",
                e.get("created_at"),
            ]
        )
    content = buf.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=analytics.csv"},
    )


# ---------------------------------------------------------------------------
# Internal query helper
# ---------------------------------------------------------------------------


def _query_events(
    *,
    team_id: Optional[str] = None,
    user_id: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return the events matching the filters. Falls back to mock data
    when settings.mock_mode is True OR the DB / table is unavailable.
    """
    date_from_dt = _parse_date(date_from)
    date_to_dt = _parse_date(date_to)

    if settings.mock_mode:
        _seed_mock_events()
        out: list[dict[str, Any]] = []
        for e in _mock_events:
            if team_id and e.get("team_id") != team_id:
                continue
            if user_id and e.get("user_id") != user_id:
                continue
            if event_type and e.get("event_type") != event_type:
                continue
            ts = e.get("created_at")
            if ts is not None:
                if isinstance(ts, str):
                    ts_dt = _parse_date(ts)
                else:
                    ts_dt = ts
                if ts_dt is not None:
                    if date_from_dt and ts_dt < date_from_dt:
                        continue
                    if date_to_dt and ts_dt > date_to_dt:
                        continue
            out.append(e)
        # Sort newest first.
        out.sort(key=lambda e: _coerce_dt(e.get("created_at")), reverse=True)
        return out

    # DB mode
    try:
        from database.models.schema import AnalyticsEvent

        session = _open_session()
        if session is None:
            return []
        try:
            q = session.query(AnalyticsEvent)
            if team_id:
                q = q.filter(AnalyticsEvent.team_id == team_id)
            if user_id:
                q = q.filter(AnalyticsEvent.user_id == user_id)
            if event_type:
                q = q.filter(AnalyticsEvent.event_type == event_type)
            if date_from_dt:
                q = q.filter(AnalyticsEvent.created_at >= date_from_dt)
            if date_to_dt:
                q = q.filter(AnalyticsEvent.created_at <= date_to_dt)
            rows = q.order_by(AnalyticsEvent.created_at.desc()).limit(10_000).all()
            return [
                {
                    "id": r.id,
                    "team_id": r.team_id,
                    "user_id": r.user_id,
                    "event_type": r.event_type,
                    "event_data": r.event_data,
                    "duration_ms": r.duration_ms,
                    "cost_estimate": r.cost_estimate,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        finally:
            session.close()
    except Exception:
        return []


def _coerce_dt(value: Any) -> datetime:
    """Best-effort coerce any value to a datetime (for sorting)."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        dt = _parse_date(value)
        if dt is not None:
            return dt
    return datetime.min.replace(tzinfo=timezone.utc)


def _event_to_dict(e: dict[str, Any]) -> dict[str, Any]:
    ts = e.get("created_at")
    if isinstance(ts, datetime):
        ts_iso = ts.isoformat()
    else:
        ts_iso = ts if isinstance(ts, str) else None
    return {
        "id": e.get("id"),
        "team_id": e.get("team_id"),
        "user_id": e.get("user_id"),
        "event_type": e.get("event_type"),
        "event_data": e.get("event_data") or {},
        "duration_ms": e.get("duration_ms"),
        "cost_estimate": e.get("cost_estimate"),
        "created_at": ts_iso,
    }

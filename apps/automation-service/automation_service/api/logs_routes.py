"""Logs FastAPI router — master prompt §38 (export diagnostics), §57 (secret
masking in logs), §73 (DevPanel Debug Logs tab), §77 (live event streaming).

Mounted under ``/logs`` in main.py. Endpoints:

* ``WebSocket /logs/stream`` — tails ``settings.log_file`` and pushes new
  lines to the client as JSON. If the log file is ``None`` (mock mode),
  falls back to streaming synthetic log events from the in-process
  :class:`EventBus` (STEP_STARTED / STEP_COMPLETED / STEP_FAILED /
  TASK_CREATED / USER_APPROVAL_REQUIRED etc.).

  Query params:
  - ``level``   — minimum level to emit (DEBUG/INFO/WARN/ERROR). Default INFO.
  - ``tool``    — only emit lines whose ``tool`` field (if present) matches.
  - ``task_id`` — only emit lines whose ``task_id`` field (if present) matches.
  - ``token``   — IPC bearer token (alternative to Authorization header).

* ``GET /logs/recent`` — returns the last ``limit`` (default 100) entries
  from the log file (or event-bus history if no log file). Same filters
  as the WebSocket.

* ``GET /logs/export`` — returns a downloadable file with filtered logs.
  Query params: ``format`` (json|csv|txt), ``since`` (ISO datetime).

CRITICAL (master prompt §57): every log line is run through
:func:`automation_service.security.credentials.mask` before being sent
or returned, so secrets in log lines are redacted.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..engine.event_bus import event_bus
from ..security.credentials import mask


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — the WebSocket uses a ``token`` query param (browsers can't set
# Authorization headers on the upgrade request). HTTP routes use the same
# verify_ipc_token dependency as everywhere else.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Lazy import of the verify_ipc_token dependency from main."""
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


def _verify_ws_token(token: Optional[str]) -> None:
    """Validate the WebSocket ``?token=`` query param.

    If ``settings.ipc_token`` is unset (dev mode), any token (including
    None) is accepted. Otherwise the supplied token must match exactly.
    """
    if settings.ipc_token is None:
        return
    if token != settings.ipc_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")


# ---------------------------------------------------------------------------
# Level helpers
# ---------------------------------------------------------------------------


_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _level_value(level: str) -> int:
    return _LEVEL_ORDER.get(level.upper(), 20)


def _level_passes(line_level: str, minimum: str) -> bool:
    return _level_value(line_level) >= _level_value(minimum)


# ---------------------------------------------------------------------------
# Log line parsing
# ---------------------------------------------------------------------------


# loguru default format: "YYYY-MM-DD HH:MM:SS.mmm | LEVEL | logger | message"
# Example: "2025-01-15 10:23:45.123 | INFO     | automation_service.api.workflow_routes | saving workflow id=abc"
_LOGURU_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*"
    r"(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<logger>[^|]+?)\s*\|\s*"
    r"(?P<message>.*)$"
)


def _parse_log_line(line: str) -> Optional[dict[str, Any]]:
    """Parse a single log line into a structured dict.

    Returns ``None`` if the line can't be parsed (e.g. multi-line stack
    trace fragments that don't match the loguru pattern). Those lines are
    attached to the previous emitted entry as continuation.
    """
    if not line or not line.strip():
        return None
    match = _LOGURU_RE.match(line.rstrip("\n"))
    if not match:
        # Treat as a free-text INFO line so the user still sees it.
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "logger": "automation-service",
            "message": line.rstrip("\n"),
            "tool": None,
            "task_id": None,
        }
    return {
        "timestamp": match.group("ts"),
        "level": match.group("level"),
        "logger": match.group("logger").strip(),
        "message": match.group("message").strip(),
        "tool": _extract_tool_name(match.group("logger"), match.group("message")),
        "task_id": _extract_task_id(match.group("message")),
    }


_TOOL_PATTERNS = [
    re.compile(r"\btool[=:\s]+['\"]?(?P<tool>[a-z_]+\.[a-z_]+)['\"]?", re.IGNORECASE),
    re.compile(r"\b(?P<tool>mouse\.[a-z_]+|keyboard\.[a-z_]+|screen\.[a-z_]+|file\.[a-z_]+|app\.[a-z_]+|browser\.[a-z_]+)\b"),
]
_TASK_ID_RE = re.compile(r"\btask_id[=:\s]+['\"]?(?P<id>[a-fA-F0-9-]{8,})['\"]?", re.IGNORECASE)


def _extract_tool_name(logger: str, message: str) -> Optional[str]:
    for pat in _TOOL_PATTERNS:
        m = pat.search(message)
        if m:
            return m.group("tool")
    # If the logger name itself looks like a tool namespace, use it.
    if "." in logger and "automation_service" not in logger:
        return logger
    return None


def _extract_task_id(message: str) -> Optional[str]:
    m = _TASK_ID_RE.search(message)
    if m:
        return m.group("id")
    return None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _passes_filters(
    entry: dict[str, Any],
    level: str,
    tool: Optional[str],
    task_id: Optional[str],
) -> bool:
    if not _level_passes(entry.get("level", "INFO"), level):
        return False
    if tool is not None and entry.get("tool") != tool:
        return False
    if task_id is not None and entry.get("task_id") != task_id:
        return False
    return True


def _mask_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Run :func:`mask` over user-facing string fields in the entry.

    Master prompt §57 — secrets must never leak through logs. However,
    infrastructure fields (``timestamp``, ``level``, ``logger``,
    ``task_id``, ``event_type``) are NOT user content and shouldn't be
    masked (otherwise the level filter on the client can't match
    "ERROR" against a redacted value).

    Only the ``message`` and ``tool`` fields can carry user-supplied
    content, so we mask only those.
    """
    out: dict[str, Any] = dict(entry)  # shallow copy preserves infra fields
    if isinstance(entry.get("message"), str):
        out["message"] = mask(entry["message"])
    if isinstance(entry.get("tool"), str) and entry["tool"]:
        # Tool names are dotted identifiers (mouse.click, etc.) — only
        # mask if it actually looks like a token, not a tool name. The
        # ``mask`` function returns "<redacted>" for short values, which
        # would clobber valid tool names. Use it only when the value
        # exceeds the typical tool-name length.
        if len(entry["tool"]) > 24:
            out["tool"] = mask(entry["tool"])
    return out


# ---------------------------------------------------------------------------
# Log file readers
# ---------------------------------------------------------------------------


def _read_recent_lines(path: Path, limit: int = 100) -> list[str]:
    """Read the last ``limit`` lines from a log file efficiently.

    Returns an empty list if the file doesn't exist or can't be read.
    """
    if path is None or not path:
        return []
    try:
        p = Path(path)
        if not p.exists():
            return []
        # Read all lines (log files are typically <10MB; tailing is fine).
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return lines[-limit:] if limit > 0 else lines
    except Exception:
        return []


def _read_all_lines(path: Path) -> list[str]:
    return _read_recent_lines(path, limit=0)


def _entries_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        entry = _parse_log_line(line)
        if entry is not None:
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Synthetic events — used when there's no log file (mock mode).
# ---------------------------------------------------------------------------


# A small ring buffer of the most recent events so /logs/recent has data
# to return even when no log file is configured. The WebSocket also pulls
# from here on connect so a fresh client sees recent history.
_EVENT_HISTORY: list[dict[str, Any]] = []
_EVENT_HISTORY_LIMIT = 500


def _record_event(event_type: str, payload: dict[str, Any]) -> None:
    """Sync handler attached to event_bus — records recent events for /logs/recent."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": _event_type_to_level(event_type),
        "logger": "automation_service.event_bus",
        "message": f"{event_type}: {json.dumps(payload, default=str)[:200]}",
        "tool": payload.get("tool") if isinstance(payload, dict) else None,
        "task_id": payload.get("task_id") if isinstance(payload, dict) else None,
        "event_type": event_type,
    }
    _EVENT_HISTORY.append(entry)
    if len(_EVENT_HISTORY) > _EVENT_HISTORY_LIMIT:
        # Trim to the most recent N entries.
        del _EVENT_HISTORY[: len(_EVENT_HISTORY) - _EVENT_HISTORY_LIMIT]


# Subscribe to the canonical event types from master prompt §76.
for _evt in (
    "TASK_CREATED",
    "TASK_STARTED",
    "TASK_PAUSED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "STEP_STARTED",
    "STEP_COMPLETED",
    "STEP_FAILED",
    "USER_APPROVAL_REQUIRED",
    "UNHANDLED_ERROR",
    "EMERGENCY_STOP",
):
    event_bus.on(_evt, lambda payload, e=_evt: _record_event(e, payload))


def _event_type_to_level(event_type: str) -> str:
    if event_type in {"TASK_FAILED", "STEP_FAILED", "UNHANDLED_ERROR", "EMERGENCY_STOP"}:
        return "ERROR"
    if event_type in {"TASK_PAUSED", "USER_APPROVAL_REQUIRED"}:
        return "WARN"
    if event_type in {"TASK_CREATED", "TASK_STARTED", "STEP_STARTED", "STEP_COMPLETED"}:
        return "INFO"
    return "INFO"


# ---------------------------------------------------------------------------
# Public entry fetcher — used by both HTTP endpoints and the WebSocket
# pre-stream flush.
# ---------------------------------------------------------------------------


def _fetch_entries(
    limit: int = 100,
    level: str = "INFO",
    tool: Optional[str] = None,
    task_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Return filtered, masked log entries.

    Pulls from ``settings.log_file`` if available; falls back to the
    in-memory event ring buffer otherwise.
    """
    log_file = settings.log_file
    if log_file is None or not Path(log_file).exists():
        entries = list(_EVENT_HISTORY)
    else:
        lines = _read_recent_lines(Path(log_file), limit=max(limit, 500))
        entries = _entries_from_lines(lines)

    # Apply filters.
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        if not _passes_filters(entry, level, tool, task_id):
            continue
        if since is not None:
            ts_str = entry.get("timestamp")
            if ts_str:
                try:
                    # Be lenient: parse with or without timezone.
                    parsed_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if parsed_ts < since:
                        continue
                except (ValueError, TypeError):
                    pass
        filtered.append(entry)

    # Apply limit AFTER filters so we get the latest N matching entries.
    if limit > 0:
        filtered = filtered[-limit:]
    # Mask every entry — master prompt §57.
    return [_mask_entry(e) for e in filtered]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str
    tool: Optional[str] = None
    task_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes — WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/stream")
async def logs_stream(
    ws: WebSocket,
    level: str = Query("INFO"),
    tool: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
) -> None:
    """Stream new log lines over a WebSocket.

    Accepts the same filters as ``GET /logs/recent``. On connect, the
    last 50 matching entries are pushed as a "backfill" so the client
    immediately sees recent context. New lines are then pushed in real
    time.

    The connection is closed if the IPC token check fails (when
    ``settings.ipc_token`` is set).
    """
    # Validate token (raises HTTPException which FastAPI converts to a
    # 401 closing handshake).
    _verify_ws_token(token)

    await ws.accept()

    # 1. Backfill — push the last 50 matching entries so the UI isn't empty.
    try:
        backfill = _fetch_entries(limit=50, level=level, tool=tool, task_id=task_id)
        await ws.send_json({"type": "backfill", "entries": backfill})
    except Exception:
        # Backfill failure shouldn't kill the connection.
        pass

    # 2. Decide whether to tail a log file or subscribe to the event bus.
    log_file = Path(settings.log_file) if settings.log_file else None
    if log_file and log_file.exists():
        await _stream_log_file(ws, log_file, level, tool, task_id)
    else:
        await _stream_event_bus(ws, level, tool, task_id)


async def _stream_log_file(
    ws: WebSocket,
    log_file: Path,
    level: str,
    tool: Optional[str],
    task_id: Optional[str],
) -> None:
    """Tail ``log_file`` and push new lines to ``ws``.

    Uses a simple polling loop (every 200ms) — async file system watchers
    (e.g. ``watchfiles``) are heavier than we need for a dev panel.
    """
    try:
        with log_file.open("r", encoding="utf-8", errors="replace") as fh:
            # Seek to end so we only push NEW lines from now on (the
            # backfill above already covered history).
            fh.seek(0, io.SEEK_END)
            while True:
                line = fh.readline()
                if not line:
                    # No new content — wait a bit.
                    await asyncio.sleep(0.2)
                    continue
                entry = _parse_log_line(line)
                if entry is None:
                    continue
                if not _passes_filters(entry, level, tool, task_id):
                    continue
                try:
                    await ws.send_json({"type": "log", "entry": _mask_entry(entry)})
                except WebSocketDisconnect:
                    return
                except Exception:
                    # Socket died — exit the loop.
                    return
    except WebSocketDisconnect:
        return
    except Exception:
        # File vanished mid-tail — degrade gracefully.
        try:
            await ws.send_json({"type": "error", "message": "log file unavailable"})
        except Exception:
            pass
        return


async def _stream_event_bus(
    ws: WebSocket,
    level: str,
    tool: Optional[str],
    task_id: Optional[str],
) -> None:
    """When there's no log file to tail, stream synthetic log entries
    derived from the in-process event bus.

    This is the mock-mode path: every STEP_STARTED / STEP_COMPLETED /
    TASK_CREATED / etc. event becomes a JSON log entry pushed to the client.
    """
    queue = event_bus.subscribe()
    try:
        while True:
            try:
                event_type, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Send a heartbeat every second so the client knows the
                # connection is alive.
                try:
                    await ws.send_json({"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()})
                except WebSocketDisconnect:
                    return
                except Exception:
                    return
                continue

            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": _event_type_to_level(event_type),
                "logger": "automation_service.event_bus",
                "message": f"{event_type}: {json.dumps(payload, default=str)[:200]}",
                "tool": payload.get("tool") if isinstance(payload, dict) else None,
                "task_id": payload.get("task_id") if isinstance(payload, dict) else None,
                "event_type": event_type,
            }
            if not _passes_filters(entry, level, tool, task_id):
                continue
            try:
                await ws.send_json({"type": "log", "entry": _mask_entry(entry)})
            except WebSocketDisconnect:
                return
            except Exception:
                return
    finally:
        # Drop the queue from the bus's subscriber list.
        try:
            event_bus._subscribers.remove(queue)  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Routes — HTTP
# ---------------------------------------------------------------------------


@router.get(
    "/recent",
    response_model=list[LogEntry],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["logs"],
)
async def logs_recent(
    limit: int = Query(100, ge=1, le=10_000),
    level: str = Query("INFO"),
    tool: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
) -> list[dict[str, Any]]:
    """Return the last ``limit`` log entries.

    In mock mode (no log file), returns synthetic entries derived from the
    in-process event bus ring buffer.
    """
    return _fetch_entries(limit=limit, level=level, tool=tool, task_id=task_id)


@router.get(
    "/export",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["logs"],
)
async def logs_export(
    format: str = Query("json", pattern="^(json|csv|txt)$"),
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    level: str = Query("INFO"),
    tool: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
):
    """Export filtered log entries as a downloadable file.

    Master prompt §38 — allow users to export diagnostic logs.
    """
    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"invalid 'since' datetime: {since!r}",
            )

    entries = _fetch_entries(limit=0, level=level, tool=tool, task_id=task_id, since=since_dt)

    if format == "json":
        content = json.dumps(entries, indent=2, default=str)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=logs.json"},
        )
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "level", "logger", "tool", "task_id", "message"])
        for e in entries:
            writer.writerow(
                [
                    e.get("timestamp", ""),
                    e.get("level", ""),
                    e.get("logger", ""),
                    e.get("tool", "") or "",
                    e.get("task_id", "") or "",
                    e.get("message", ""),
                ]
            )
        content = buf.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=logs.csv"},
        )
    # txt
    lines = []
    for e in entries:
        lines.append(
            f"{e.get('timestamp', '')} [{e.get('level', 'INFO')}] "
            f"{e.get('logger', '')}: {e.get('message', '')}"
        )
    content = "\n".join(lines)
    return StreamingResponse(
        iter([content]),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=logs.txt"},
    )

"""FastAPI router for system-level operations — master prompt sections
47 (system tray), 90 (auto-update), 91 (backup).

Mounted under ``/system`` in main.py. All routes require the IPC bearer
token (resolved lazily from ``automation_service.main`` to avoid the
circular import).

Endpoints
---------

Version + tray state:
* ``GET  /system/version``         — returns {version, git_commit, build_date}.
* ``GET  /system/tray/state``      — returns {state: idle|running|paused|error}.

Auto-update (section 90):
* ``GET  /system/updates/check``   — calls UpdateManager.check_for_updates().
* ``POST /system/updates/download`` — body: {update_info} — downloads + returns the local path.
* ``POST /system/updates/apply``    — body: {file_path} — applies the update.
* ``POST /system/updates/rollback`` — rolls back to the previous version.
* ``GET  /system/updates/history``  — returns the update history list.

Backup (section 91):
* ``POST   /system/backup``                — body: {destination?} — creates a backup.
* ``POST   /system/backup/restore``        — body: {archive_path} — restores.
* ``GET    /system/backup/list``           — lists backups.
* ``DELETE /system/backup/{filename}``      — deletes a backup.
* ``POST   /system/backup/schedule``       — body: {cron} — schedules automatic backups.
* ``DELETE /system/backup/schedule/{job_id}`` — cancels a scheduled backup.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..backup.manager import backup_manager
from ..config import settings
from ..update.manager import UpdateInfo, update_manager


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency (lazy to avoid circular import with automation_service.main)
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    """Resolve ``verify_ipc_token`` from main lazily.

    The actual implementation lives in :mod:`automation_service.main`.
    We look it up at request time so importing this router doesn't
    pull in the FastAPI app before all subsystems register.
    """
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Tray state — in-memory mirror of what the Electron main process reports.
# ---------------------------------------------------------------------------


# The Electron main process is the source of truth for tray state, but
# the service exposes a ``GET /system/tray/state`` endpoint so other
# clients (CLI, MCP) can query it. We store the last-known state set
# via ``POST /system/tray/state`` (or default to "idle").
_tray_state: str = "idle"


class TrayStateRequest(BaseModel):
    """Body for ``POST /system/tray/state`` — set the tray state."""

    state: str = Field(..., description="idle|running|paused|error")


class TrayStateResponse(BaseModel):
    state: str


# ---------------------------------------------------------------------------
# Version + tray state routes
# ---------------------------------------------------------------------------


@router.get("/version", dependencies=[Depends(_verify_ipc_token)])
async def get_version() -> dict:
    """Return the service version, git commit (best-effort), and build date.

    Used by the Electron app's About dialog and the auto-update
    pipeline (to compare against the latest release).
    """
    git_commit = os.getenv("GIT_COMMIT") or _read_git_commit()
    build_date = os.getenv("BUILD_DATE") or datetime.now(timezone.utc).isoformat()
    return {
        "version": settings.service_version,
        "git_commit": git_commit,
        "build_date": build_date,
    }


@router.get(
    "/tray/state",
    response_model=TrayStateResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def get_tray_state() -> dict:
    """Return the last-known tray state (idle/running/paused/error)."""
    return {"state": _tray_state}


@router.post(
    "/tray/state",
    response_model=TrayStateResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def set_tray_state(req: TrayStateRequest) -> dict:
    """Set the tray state (called by the Electron main process)."""
    global _tray_state
    if req.state not in {"idle", "running", "paused", "error"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid tray state: {req.state}",
        )
    _tray_state = req.state
    return {"state": _tray_state}


# ---------------------------------------------------------------------------
# Auto-update routes — master prompt section 90
# ---------------------------------------------------------------------------


@router.get(
    "/updates/check",
    dependencies=[Depends(_verify_ipc_token)],
)
async def check_for_updates() -> dict:
    """Check the update server for a newer release.

    Returns the :class:`UpdateInfo` if a newer version is available, or
    ``{"update": None}`` when the current version is up to date.

    In mock mode (default), returns a deterministic fake
    :class:`UpdateInfo` after a 1-second delay.
    """
    info = await update_manager.check_for_updates()
    if info is None:
        return {"update": None, "current_version": update_manager.get_current_version()}
    return {
        "update": info.model_dump(mode="json"),
        "current_version": update_manager.get_current_version(),
    }


@router.post(
    "/updates/download",
    dependencies=[Depends(_verify_ipc_token)],
)
async def download_update(update_info: UpdateInfo) -> dict:
    """Download an update and return the local file path.

    Verifies SHA256 + signature before returning the path. Raises 400
    if either verification fails (section 90 invariant: never apply
    unsigned updates).
    """
    try:
        path = await update_manager.download_update(update_info)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"update verification failed: {exc}",
        )
    return {"file_path": str(path)}


class ApplyRequest(BaseModel):
    file_path: str = Field(..., description="Path to the downloaded update file")


@router.post(
    "/updates/apply",
    dependencies=[Depends(_verify_ipc_token)],
)
async def apply_update(req: ApplyRequest) -> dict:
    """Apply a previously-downloaded update.

    Re-verifies the file on disk before applying. Raises 400 if
    verification fails.
    """
    try:
        await update_manager.apply_update(Path(req.file_path))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"update verification failed: {exc}",
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"update file not found: {exc}",
        )
    return {"applied": True}


@router.post(
    "/updates/rollback",
    dependencies=[Depends(_verify_ipc_token)],
)
async def rollback_update() -> dict:
    """Roll back to the previously-applied version."""
    await update_manager.rollback_update()
    return {"rolled_back": True}


@router.get(
    "/updates/history",
    dependencies=[Depends(_verify_ipc_token)],
)
async def update_history() -> dict:
    """Return the update history list."""
    return {"history": update_manager.get_update_history()}


# ---------------------------------------------------------------------------
# Backup routes — master prompt section 91
# ---------------------------------------------------------------------------


class CreateBackupRequest(BaseModel):
    destination: Optional[str] = Field(
        None,
        description="Directory or full file path. Default: /home/z/my-project/backups/",
    )


class CreateBackupResponse(BaseModel):
    archive_path: str
    size_bytes: int
    mock_mode: bool


@router.post(
    "/backup",
    response_model=CreateBackupResponse,
    dependencies=[Depends(_verify_ipc_token)],
)
async def create_backup(req: CreateBackupRequest) -> dict:
    """Create a backup archive and return its path.

    CRITICAL (section 91): the archive will NEVER contain plaintext
    secrets — the ``api_credentials`` table is skipped entirely.
    """
    dest = Path(req.destination) if req.destination else None
    archive = await backup_manager.create_backup(destination=dest)
    size = archive.stat().st_size
    return {
        "archive_path": str(archive),
        "size_bytes": size,
        "mock_mode": settings.mock_mode,
    }


class RestoreBackupRequest(BaseModel):
    archive_path: str = Field(..., description="Path to the backup archive")


@router.post(
    "/backup/restore",
    dependencies=[Depends(_verify_ipc_token)],
)
async def restore_backup(req: RestoreBackupRequest) -> dict:
    """Restore from a backup archive. Returns a summary dict."""
    try:
        summary = await backup_manager.restore_backup(Path(req.archive_path))
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"backup archive not found: {exc}",
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid archive: {exc}",
        )
    return summary


@router.get(
    "/backup/list",
    dependencies=[Depends(_verify_ipc_token)],
)
async def list_backups() -> dict:
    """List all backup archives in the default backup dir."""
    infos = await backup_manager.list_backups()
    return {
        "backups": [info.model_dump(mode="json") for info in infos],
        "count": len(infos),
    }


@router.delete(
    "/backup/{filename}",
    dependencies=[Depends(_verify_ipc_token)],
)
async def delete_backup(filename: str) -> dict:
    """Delete a backup archive by filename (basename only, no path traversal)."""
    # Guard against path traversal — only allow basenames.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "filename must be a basename (no path separators or '..')",
        )
    target = backup_manager.backup_dir / filename
    ok = await backup_manager.delete_backup(target)
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"backup archive not found: {filename}",
        )
    return {"deleted": True, "filename": filename}


class ScheduleBackupRequest(BaseModel):
    cron: str = Field(
        "0 2 * * *",
        description="Cron expression (default: daily at 2 AM)",
    )


@router.post(
    "/backup/schedule",
    dependencies=[Depends(_verify_ipc_token)],
)
async def schedule_backup(req: ScheduleBackupRequest) -> dict:
    """Schedule automatic backups via APScheduler. Returns the job_id."""
    job_id = await backup_manager.schedule_automatic_backups(req.cron)
    return {"job_id": job_id, "cron": req.cron}


@router.delete(
    "/backup/schedule/{job_id}",
    dependencies=[Depends(_verify_ipc_token)],
)
async def cancel_scheduled_backup(job_id: str) -> dict:
    """Cancel a scheduled backup job. Returns True if it existed."""
    ok = await backup_manager.cancel_automatic_backups(job_id)
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"scheduled backup job not found: {job_id}",
        )
    return {"cancelled": True, "job_id": job_id}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_git_commit() -> str:
    """Best-effort read of the current git commit SHA.

    Returns an empty string if git isn't available or the project
    isn't a git repo (e.g. when running from a tarball install).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(settings.project_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""

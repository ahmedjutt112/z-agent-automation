"""Files FastAPI router — master prompt §18 (file automation), §55 (file
security).

Mounted under ``/files`` in main.py. Endpoints:

* ``GET    /files/list?path=...``        — list files in a directory
* ``GET    /files/read?path=...``        — read a file's contents
* ``POST   /files/write``                — write text to a file
* ``POST   /files/move``                 — move a file
* ``POST   /files/rename``               — rename a file in place
* ``POST   /files/copy``                 — copy a file
* ``POST   /files/delete``               — delete a file (CRITICAL risk)
* ``GET    /files/download?path=...``    — download a file's raw bytes

Path safety — master prompt §55 File Security:
    Every route validates the target path through
    :func:`automation_service.tools.files._validate_path`, which enforces
    an allowlist of roots and blocks system directories (``/etc``,
    ``/usr``, ``C:/Windows`` etc.). Blocked paths return ``403``.

All routes require the IPC bearer token.
"""

from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..tools.files import _validate_path


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


class WriteRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class MoveRequest(BaseModel):
    source: str
    destination: str


class RenameRequest(BaseModel):
    path: str
    new_name: str


class CopyRequest(BaseModel):
    source: str
    destination: str


class DeleteRequest(BaseModel):
    path: str
    approved: bool = Field(
        default=False,
        description=(
            "Master prompt §9 / §10 — file.delete is CRITICAL risk and "
            "requires explicit user approval. The route returns 403 when "
            "approved=False so the UI can render a confirmation modal."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe(path: str, must_exist: bool = False) -> Path:
    """Resolve ``path`` through the security validator or raise 403."""
    try:
        return _validate_path(path, must_exist=must_exist)
    except PermissionError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            str(exc),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            str(exc),
        )


def _entry_dict(p: Path, base: Path) -> dict[str, Any]:
    stat = p.stat()
    return {
        "name": p.name,
        "path": str(p),
        "relative": str(p.relative_to(base)) if p != base else ".",
        "is_dir": p.is_dir(),
        "size": stat.st_size if not p.is_dir() else 0,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "extension": p.suffix.lower() if p.is_file() else "",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/list",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_list(
    path: str = Query(..., description="Absolute or ~-prefixed path to list."),
    pattern: str = Query("*", description="Glob pattern."),
) -> dict[str, Any]:
    """List files + directories under ``path``."""
    p = _safe(path, must_exist=True)
    if not p.is_dir():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"path is not a directory: {p}",
        )
    entries = [_entry_dict(child, p) for child in sorted(p.glob(pattern))]
    return {
        "path": str(p),
        "count": len(entries),
        "entries": entries,
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/read",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_read(
    path: str = Query(...),
    encoding: str = Query("utf-8"),
    max_bytes: int = Query(1_048_576, ge=1, le=10_485_760),
) -> dict[str, Any]:
    """Read a file's contents."""
    p = _safe(path, must_exist=True)
    if not p.is_file():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"path is not a regular file: {p}",
        )
    data = p.read_bytes()[:max_bytes]
    text = data.decode(encoding, errors="replace")
    return {
        "path": str(p),
        "size": len(data),
        "text": text,
        "encoding": encoding,
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/write",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["files"],
)
async def files_write(req: WriteRequest) -> dict[str, Any]:
    """Write text to a file (overwrites)."""
    p = _safe(req.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(req.content, encoding=req.encoding)
    return {
        "path": str(p),
        "size": len(req.content),
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/move",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_move(req: MoveRequest) -> dict[str, Any]:
    """Move a file from source to destination."""
    src = _safe(req.source, must_exist=True)
    dst = _safe(req.destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {
        "source": str(src),
        "destination": str(dst),
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/rename",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_rename(req: RenameRequest) -> dict[str, Any]:
    """Rename a file in place (keeps its directory)."""
    p = _safe(req.path, must_exist=True)
    new_path = p.parent / req.new_name
    new_path = _safe(str(new_path))
    p.rename(new_path)
    return {
        "old": str(p),
        "new": str(new_path),
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/copy",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["files"],
)
async def files_copy(req: CopyRequest) -> dict[str, Any]:
    """Copy a file from source to destination.

    Uses ``shutil.copy2`` so the destination inherits mtime + mode bits.
    """
    src = _safe(req.source, must_exist=True)
    dst = _safe(req.destination)
    if not src.is_file():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"source is not a regular file: {src}",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return {
        "source": str(src),
        "destination": str(dst),
        "size": dst.stat().st_size,
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/delete",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_delete(req: DeleteRequest) -> dict[str, Any]:
    """Delete a file. CRITICAL risk — requires explicit approval.

    Master prompt §9 / §10 — file.delete is CRITICAL risk. The route
    refuses to delete unless ``req.appoved=True`` so the UI can render
    a confirmation modal and resubmit with the flag set.
    """
    if not req.approved:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "file.delete is CRITICAL risk — pass approved=true to confirm",
        )
    p = _safe(req.path, must_exist=True)
    if not p.is_file():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"path is not a regular file: {p}",
        )
    try:
        p.unlink()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"failed to delete: {exc}",
        )
    return {
        "path": str(p),
        "deleted": True,
        "mock_mode": bool(settings.mock_mode),
    }


@router.get(
    "/download",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["files"],
)
async def files_download(path: str = Query(...)) -> FileResponse:
    """Return the raw bytes of a file as a downloadable attachment."""
    p = _safe(path, must_exist=True)
    if not p.is_file():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"path is not a regular file: {p}",
        )
    return FileResponse(
        str(p),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{p.name}"'},
    )

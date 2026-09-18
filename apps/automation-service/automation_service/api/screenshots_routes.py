"""Screenshots FastAPI router — master prompt §15 (OCR), §73 (DevPanel
Screenshots + OCR boxes tabs).

Mounted under ``/screenshots`` in main.py. Endpoints:

* ``GET /screenshots`` — list recent screenshots (DB rows OR filesystem
  fallback to ``settings.screenshots_dir``).
* ``GET /screenshots/recent`` — shortcut for ``GET /screenshots?limit=10``.
* ``GET /screenshots/{id}`` — return the raw image file (image/png).
* ``GET /screenshots/{id}/metadata`` — return just the metadata dict.
* ``DELETE /screenshots/{id}`` — delete the DB row + the file on disk.
* ``POST /screenshots/{id}/ocr`` — run the existing ``screen.ocr`` tool
  against the screenshot file and return text + bounding boxes.

Routes are ordered so ``/recent`` is registered BEFORE ``/{screenshot_id}``
(otherwise FastAPI would capture "recent" as the id).

All routes require the IPC bearer token.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..engine.tool_registry import tool_registry


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency (lazy import — avoid circular dep with main)
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ScreenshotMetadata(BaseModel):
    id: str
    task_id: Optional[str] = None
    profile_id: Optional[str] = None
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime


class OcrBoundingBox(BaseModel):
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float


class OcrResult(BaseModel):
    text: str
    bounding_boxes: list[OcrBoundingBox]


class DeleteResponse(BaseModel):
    id: str
    deleted: bool


# ---------------------------------------------------------------------------
# DB helpers — gracefully degrade to filesystem scan when no DB rows exist
# ---------------------------------------------------------------------------


def _list_from_db(
    limit: int,
    task_id: Optional[str],
    profile_id: Optional[str],
) -> list[dict[str, Any]]:
    """Query the ``screenshots`` table for the most recent rows.

    Returns ``[]`` if the DB isn't reachable (e.g. mock mode without a
    configured DB file). Profile and task filters are applied at the
    query layer when supplied.
    """
    try:
        from database.base import SessionLocal
        from database.models.schema import Screenshot
    except ImportError:
        return []

    out: list[dict[str, Any]] = []
    try:
        with SessionLocal() as session:
            q = session.query(Screenshot)
            if task_id is not None:
                q = q.filter(Screenshot.task_id == task_id)
            if profile_id is not None:
                q = q.filter(Screenshot.profile_id == profile_id)
            rows = q.order_by(Screenshot.created_at.desc()).limit(limit).all()
            for r in rows:
                out.append(
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "profile_id": r.profile_id,
                        "file_path": r.file_path,
                        "width": r.width,
                        "height": r.height,
                        "metadata_json": r.metadata_json or {},
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
    except Exception:
        # DB unavailable — caller will fall back to filesystem scan.
        return []
    return out


def _list_from_filesystem(
    limit: int,
    task_id: Optional[str],
    profile_id: Optional[str],
) -> list[dict[str, Any]]:
    """Fallback: scan ``settings.screenshots_dir`` for PNG files.

    Filesystem rows obviously can't carry ``task_id`` / ``profile_id``
    filters (no DB), so those filters are best-effort here: when set,
    we attempt to parse ``task_<id>__profile_<pid>.png`` filenames; if
    that fails, we skip the filter and return everything (limit N).
    """
    out: list[dict[str, Any]] = []
    sdir = settings.screenshots_dir
    if not sdir.exists():
        return out

    # Sort by modification time descending, then take the top ``limit``.
    files = sorted(sdir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[:limit]:
        # Try to parse task_id / profile_id from the filename.
        name = p.stem
        parsed_task: Optional[str] = None
        parsed_profile: Optional[str] = None
        if "task_" in name:
            # Best-effort: pull everything after "task_" up to the next separator.
            try:
                rest = name.split("task_", 1)[1]
                parsed_task = rest.split("__", 1)[0].split("_", 1)[0]
            except Exception:
                pass
        if "profile_" in name:
            try:
                rest = name.split("profile_", 1)[1]
                parsed_profile = rest.split("__", 1)[0].split("_", 1)[0]
            except Exception:
                pass

        if task_id is not None and parsed_task != task_id:
            continue
        if profile_id is not None and parsed_profile != profile_id:
            continue

        stat = p.stat()
        out.append(
            {
                "id": p.stem,  # use the filename (sans extension) as id
                "task_id": parsed_task,
                "profile_id": parsed_profile,
                "file_path": str(p),
                "width": None,  # unknown without reading the image header
                "height": None,
                "metadata_json": {"source": "filesystem", "size_bytes": stat.st_size},
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out


def _list_screenshots(
    limit: int,
    task_id: Optional[str],
    profile_id: Optional[str],
) -> list[dict[str, Any]]:
    """Try the DB first; fall back to filesystem scan if it has no rows.

    Master prompt §73 — the DevPanel Screenshots tab must show recent
    screenshots even when the DB hasn't been populated (e.g. mock mode
    writes files but never inserts rows).
    """
    rows = _list_from_db(limit, task_id, profile_id)
    if rows:
        return rows
    return _list_from_filesystem(limit, task_id, profile_id)


def _resolve_screenshot_file(screenshot_id: str) -> Optional[Path]:
    """Return the on-disk path for a screenshot id.

    Tries the DB first; falls back to ``settings.screenshots_dir / f"{id}.png"``.
    Returns ``None`` if neither resolves to an existing file.
    """
    # 1. DB lookup — best-effort.
    try:
        from database.base import SessionLocal
        from database.models.schema import Screenshot

        with SessionLocal() as session:
            # Try as UUID first; if it doesn't match, try as a filename stem.
            row = session.query(Screenshot).filter(Screenshot.id == screenshot_id).first()
            if row is not None:
                p = Path(row.file_path)
                if p.exists():
                    return p
    except Exception:
        pass

    # 2. Filesystem fallback.
    if screenshot_id.endswith(".png"):
        candidate = settings.screenshots_dir / screenshot_id
    else:
        candidate = settings.screenshots_dir / f"{screenshot_id}.png"
    if candidate.exists():
        return candidate
    return None


def _load_screenshot_or_404(screenshot_id: str) -> Path:
    """Resolve the file or raise 404."""
    p = _resolve_screenshot_file(screenshot_id)
    if p is None or not p.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"screenshot '{screenshot_id}' not found",
        )
    return p


# ---------------------------------------------------------------------------
# IMPORTANT: /recent is declared BEFORE /{screenshot_id} so FastAPI doesn't
# capture "recent" as the id path param.
# ---------------------------------------------------------------------------


@router.get(
    "/recent",
    response_model=list[ScreenshotMetadata],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def screenshots_recent() -> list[dict[str, Any]]:
    """Shortcut for ``GET /screenshots?limit=10``."""
    return _list_screenshots(limit=10, task_id=None, profile_id=None)


@router.get(
    "",
    response_model=list[ScreenshotMetadata],
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def list_screenshots(
    limit: int = Query(50, ge=1, le=500),
    task_id: Optional[str] = Query(None),
    profile_id: Optional[str] = Query(None),
) -> list[dict[str, Any]]:
    """List recent screenshots.

    Pulls from the ``screenshots`` DB table when available; falls back to
    scanning ``settings.screenshots_dir`` for ``*.png`` files when no DB
    rows exist (e.g. mock mode writes files but skips the DB insert).
    """
    return _list_screenshots(limit=limit, task_id=task_id, profile_id=profile_id)


@router.get(
    "/{screenshot_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def get_screenshot(screenshot_id: str) -> FileResponse:
    """Return the raw PNG image bytes.

    Sets ``Content-Type: image/png`` and a ``Content-Disposition`` of
    ``inline`` so the browser displays it inline rather than downloading.
    """
    p = _load_screenshot_or_404(screenshot_id)
    return FileResponse(
        str(p),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={p.name}"},
    )


@router.get(
    "/{screenshot_id}/metadata",
    response_model=ScreenshotMetadata,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def get_screenshot_metadata(screenshot_id: str) -> dict[str, Any]:
    """Return just the metadata for a screenshot (no image bytes)."""
    p = _load_screenshot_or_404(screenshot_id)
    stat = p.stat()
    # Try DB lookup for richer metadata; otherwise synthesize from filesystem.
    row: Optional[dict[str, Any]] = None
    try:
        from database.base import SessionLocal
        from database.models.schema import Screenshot

        with SessionLocal() as session:
            r = session.query(Screenshot).filter(Screenshot.id == screenshot_id).first()
            if r is not None:
                row = {
                    "id": r.id,
                    "task_id": r.task_id,
                    "profile_id": r.profile_id,
                    "file_path": r.file_path,
                    "width": r.width,
                    "height": r.height,
                    "metadata_json": r.metadata_json or {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
    except Exception:
        pass

    if row is None:
        row = {
            "id": screenshot_id,
            "task_id": None,
            "profile_id": None,
            "file_path": str(p),
            "width": None,
            "height": None,
            "metadata_json": {"source": "filesystem", "size_bytes": stat.st_size},
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
    return row


@router.delete(
    "/{screenshot_id}",
    response_model=DeleteResponse,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def delete_screenshot(screenshot_id: str) -> dict[str, Any]:
    """Delete the screenshot file + DB row.

    Returns 200 even if the DB row didn't exist (as long as the file was
    on disk and is now gone). Returns 404 if neither exists.
    """
    p = _resolve_screenshot_file(screenshot_id)
    if p is None:
        # Maybe there's a DB row without a file — try deleting the row.
        deleted_row = False
        try:
            from database.base import SessionLocal
            from database.models.schema import Screenshot

            with SessionLocal() as session:
                row = session.query(Screenshot).filter(Screenshot.id == screenshot_id).first()
                if row is not None:
                    session.delete(row)
                    session.commit()
                    deleted_row = True
        except Exception:
            pass
        if not deleted_row:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"screenshot '{screenshot_id}' not found",
            )
        return {"id": screenshot_id, "deleted": True}

    # File exists — delete it.
    try:
        p.unlink()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"failed to delete screenshot file: {exc}",
        )

    # Best-effort: delete the DB row too.
    try:
        from database.base import SessionLocal
        from database.models.schema import Screenshot

        with SessionLocal() as session:
            row = session.query(Screenshot).filter(Screenshot.id == screenshot_id).first()
            if row is not None:
                session.delete(row)
                session.commit()
    except Exception:
        pass

    return {"id": screenshot_id, "deleted": True}


@router.post(
    "/{screenshot_id}/ocr",
    response_model=OcrResult,
    dependencies=[Depends(_verify_ipc_token)],
    tags=["screenshots"],
)
async def screenshot_ocr(screenshot_id: str) -> dict[str, Any]:
    """Run OCR on a screenshot, returning text + bounding boxes.

    Uses the existing ``screen.ocr`` tool from the registry so the same
    OCR backend (pytesseract in real mode, mock in mock mode) is reused.
    """
    p = _load_screenshot_or_404(screenshot_id)
    tool = tool_registry.get("screen.ocr")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "screen.ocr tool not registered",
        )
    # Invoke the tool with the resolved image_path.
    try:
        result = await tool.execute({"image_path": str(p)})
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"OCR failed: {exc}",
        )

    if result.status.value != "completed":
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"OCR tool did not complete: {result.error or 'unknown error'}",
        )

    output = result.output or {}
    # Normalize bounding boxes — the screen.ocr tool already returns them
    # in the right shape, but be defensive in case the mock path returns {}
    # (in which case we just return empty lists).
    boxes = output.get("bounding_boxes") or []
    out_boxes: list[dict[str, Any]] = []
    for b in boxes:
        if not isinstance(b, dict):
            continue
        out_boxes.append(
            {
                "text": str(b.get("text", "")),
                "x": int(b.get("x", 0)),
                "y": int(b.get("y", 0)),
                "width": int(b.get("width", 0)),
                "height": int(b.get("height", 0)),
                "confidence": float(b.get("confidence", 0.0)),
            }
        )
    return {
        "text": str(output.get("text", "")),
        "bounding_boxes": out_boxes,
    }

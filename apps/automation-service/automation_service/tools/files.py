"""File tools — master prompt §18 (file automation), §55 (file security).

Path safety: master prompt §55 File Security requires path validation,
traversal protection, allowed directories, blocked system directories.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


# ---------------------------------------------------------------------------
# Path safety — master prompt §55 File Security
# ---------------------------------------------------------------------------

ALLOWED_ROOTS: list[Path] = [
    settings.project_root / "download",
    settings.project_root / "upload",
    settings.project_root / "workflows",
    settings.project_root / "templates",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Pictures",
]

BLOCKED_PATHS: list[Path] = [
    # NOTE: ``Path("/")`` is intentionally NOT in this list — every absolute
    # path on POSIX is a descendant of ``/`` so listing it would block all
    # paths. The ALLOWED_ROOTS allowlist below is the real gatekeeper.
    Path("/etc"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/var"),
    Path("/sys"),
    Path("/proc"),
    Path("/boot"),
    Path("/dev"),
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/System32"),
    Path("C:/Users") / os.getenv("USERNAME", "Default") / "AppData",
]


def _validate_path(target: str | Path, must_exist: bool = False, allow_blocked: bool = False) -> Path:
    """Resolve and validate a path against the security policy."""
    p = Path(target).expanduser().resolve()

    if not allow_blocked:
        for blocked in BLOCKED_PATHS:
            try:
                if p == blocked or blocked in p.parents:
                    raise PermissionError(f"Access denied: path '{p}' is in a blocked location")
            except (TypeError, ValueError):
                continue

    allowed = any(p == root or root in p.parents for root in ALLOWED_ROOTS)
    if not allowed:
        raise PermissionError(
            f"Access denied: path '{p}' is outside the allowed directories. "
            f"Allowed roots: {[str(r) for r in ALLOWED_ROOTS]}"
        )

    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")

    return p


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool
class FileReadTool(Tool):
    name = "file.read"
    description = "Read the contents of a file."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 5_000
    verification_strategy = "file_exists"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "encoding": {"type": "string", "default": "utf-8"},
            "max_bytes": {"type": "integer", "default": 1048576},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            p = _validate_path(args["path"], must_exist=True)
            encoding = args.get("encoding", "utf-8")
            max_bytes = int(args.get("max_bytes", 1_048_576))
            data = p.read_bytes()[:max_bytes]
            text = data.decode(encoding, errors="replace")
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"path": str(p), "size": len(data), "text": text[:5000]},  # truncate to 5K for log
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class FileWriteTool(Tool):
    name = "file.write"
    description = "Write text to a file (overwrites)."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 5_000
    rollback_strategy = "delete_file"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            p = _validate_path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            encoding = args.get("encoding", "utf-8")
            p.write_text(args["content"], encoding=encoding)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"path": str(p), "size": len(args["content"])},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class FileMoveTool(Tool):
    name = "file.move"
    description = "Move a file from source to destination."
    permission_level = "allow_once"
    risk_level = "medium"
    rollback_strategy = "move_back"
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            src = _validate_path(args["source"], must_exist=True)
            dst = _validate_path(args["destination"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"source": str(src), "destination": str(dst)},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class FileRenameTool(Tool):
    name = "file.rename"
    description = "Rename a file in place (keeps its directory)."
    permission_level = "allow_once"
    risk_level = "medium"
    rollback_strategy = "rename_back"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "new_name": {"type": "string"},
        },
        "required": ["path", "new_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            p = _validate_path(args["path"], must_exist=True)
            new_path = p.parent / args["new_name"]
            p.rename(new_path)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"old": str(p), "new": str(new_path)},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class FileListTool(Tool):
    name = "file.list"
    description = "List files in a directory."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 3_000
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pattern": {"type": "string", "default": "*"},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        try:
            p = _validate_path(args["path"], must_exist=True)
            pattern = args.get("pattern", "*")
            files = [str(f.relative_to(p)) for f in p.glob(pattern) if f.is_file()]
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"path": str(p), "count": len(files), "files": files[:1000]},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

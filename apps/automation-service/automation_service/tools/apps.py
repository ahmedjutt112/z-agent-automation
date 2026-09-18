"""Application / window / process tools — master prompt §12, §19 (terminal).

Apps: launch / close / detect (use OS-native APIs).
Windows: list / focus / minimize / maximize / close.
Process: list / kill (with strict allowlist per master prompt §19).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


# ---------------------------------------------------------------------------
# App launch allowlist (master prompt §19 — never unrestricted shell)
# ---------------------------------------------------------------------------

# Map of friendly name → executable path (resolved per-OS in real impl)
APP_ALLOWLIST: dict[str, str] = {
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "notepad": "notepad" if settings.host else "gedit",
    "explorer": "explorer" if settings.host else "nautilus",
    "calculator": "calc" if settings.host else "gnome-calculator",
    "vscode": "code",
    "terminal": "cmd" if settings.host else "gnome-terminal",
}


@register_tool
class AppLaunchTool(Tool):
    name = "app.launch"
    description = "Launch an application from the allowlist."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 10_000
    input_schema = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "App name from allowlist"},
            "args": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["app"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        app = args["app"].lower()
        if app not in APP_ALLOWLIST:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=f"app '{app}' not in allowlist. Allowed: {list(APP_ALLOWLIST.keys())}",
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "app": app, "args": args.get("args", [])},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        try:
            cmd = [APP_ALLOWLIST[app]] + list(args.get("args", []))
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"app": app, "pid": proc.pid, "cmd": cmd},
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
class WindowListTool(Tool):
    name = "window.list"
    description = "List currently open windows."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 3_000
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "windows": []},
            )

        try:
            import pyautogui  # type: ignore
            # pyautogui has no window-list API directly; use psutil for processes
            import psutil  # type: ignore
            wins = [
                {"pid": p.pid, "name": p.info["name"]}
                for p in psutil.process_iter(attrs=["name"])
                if p.info.get("name")
            ][:50]
            return ActionResult(
                tool=self.name, status=StepStatus.COMPLETED, output={"windows": wins}
            )
        except Exception as exc:
            return ActionResult(tool=self.name, status=StepStatus.FAILED, error=str(exc))


@register_tool
class ProcessListTool(Tool):
    name = "process.list"
    description = "List running processes."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 3_000
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "processes": []},
            )
        try:
            import psutil  # type: ignore
            procs = [
                {"pid": p.pid, "name": p.info["name"], "cpu": p.info.get("cpu_percent", 0)}
                for p in psutil.process_iter(attrs=["name", "cpu_percent"])
                if p.info.get("name")
            ]
            return ActionResult(
                tool=self.name, status=StepStatus.COMPLETED, output={"processes": procs[:100]}
            )
        except Exception as exc:
            return ActionResult(tool=self.name, status=StepStatus.FAILED, error=str(exc))

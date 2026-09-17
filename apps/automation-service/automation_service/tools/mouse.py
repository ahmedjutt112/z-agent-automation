"""Mouse tools — master prompt §12.

All tools run in mock mode by default (settings.mock_mode=True). To enable
real execution, set AUTOMATION_MOCK_MODE=false in .env and install pyautogui.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


@register_tool
class MouseClickTool(Tool):
    name = "mouse.click"
    description = "Click at screen coordinates (x, y) with the given button."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 5_000
    input_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "minimum": 0},
            "y": {"type": "integer", "minimum": 0},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            "clicks": {"type": "integer", "minimum": 1, "default": 1},
        },
        "required": ["x", "y"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        x, y = int(args["x"]), int(args["y"])
        button = args.get("button", "left")
        clicks = int(args.get("clicks", 1))

        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "x": x, "y": y, "button": button, "clicks": clicks},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        try:
            import pyautogui  # type: ignore
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"x": x, "y": y, "button": button, "clicks": clicks},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name,
                status=StepStatus.FAILED,
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )


@register_tool
class MouseMoveTool(Tool):
    name = "mouse.move"
    description = "Move the mouse cursor to (x, y) without clicking."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 2_000
    input_schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "required": ["x", "y"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        x, y = int(args["x"]), int(args["y"])
        if not settings.mock_mode:
            try:
                import pyautogui  # type: ignore
                pyautogui.moveTo(x, y)
            except Exception as exc:
                return ActionResult(tool=self.name, status=StepStatus.FAILED, error=str(exc))
        return ActionResult(
            tool=self.name,
            status=StepStatus.COMPLETED,
            output={"x": x, "y": y, "simulated": settings.mock_mode},
        )


@register_tool
class MouseScrollTool(Tool):
    name = "mouse.scroll"
    description = "Scroll the mouse wheel by N clicks (positive = up)."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 2_000
    input_schema = {
        "type": "object",
        "properties": {"amount": {"type": "integer", "default": 1}},
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        amount = int(args.get("amount", 1))
        if not settings.mock_mode:
            try:
                import pyautogui  # type: ignore
                pyautogui.scroll(amount)
            except Exception as exc:
                return ActionResult(tool=self.name, status=StepStatus.FAILED, error=str(exc))
        return ActionResult(
            tool=self.name,
            status=StepStatus.COMPLETED,
            output={"amount": amount, "simulated": settings.mock_mode},
        )

"""Keyboard tools — master prompt §12."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


@register_tool
class KeyboardTypeTool(Tool):
    name = "keyboard.type"
    description = "Type a string of text."
    permission_level = "allow_once"
    risk_level = "medium"  # typing can submit forms / send messages
    timeout_ms = 10_000
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        text = str(args["text"])
        start = datetime.now(timezone.utc)
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "text": text, "length": len(text)},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            import pyautogui  # type: ignore
            pyautogui.typewrite(text, interval=0.02)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"text": text, "length": len(text)},
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
class KeyboardHotkeyTool(Tool):
    name = "keyboard.hotkey"
    description = "Press a hotkey combination (e.g. ['ctrl', 'c'])."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 2_000
    input_schema = {
        "type": "object",
        "properties": {
            "keys": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["keys"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        keys = list(args.get("keys", []))
        if not settings.mock_mode:
            try:
                import pyautogui  # type: ignore
                pyautogui.hotkey(*keys)
            except Exception as exc:
                return ActionResult(tool=self.name, status=StepStatus.FAILED, error=str(exc))
        return ActionResult(
            tool=self.name,
            status=StepStatus.COMPLETED,
            output={"keys": keys, "simulated": settings.mock_mode},
        )

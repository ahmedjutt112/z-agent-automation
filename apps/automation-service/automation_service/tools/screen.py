"""Screen tools — master prompt §14 (screen understanding), §15 (OCR)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


@register_tool
class ScreenCaptureTool(Tool):
    name = "screen.capture"
    description = "Take a screenshot. Returns the saved file path."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 3_000
    input_schema = {
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
            },
            "filename": {"type": "string"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        import os
        start = datetime.now(timezone.utc)
        filename = args.get("filename") or f"screenshot_{int(start.timestamp())}.png"
        path = settings.screenshots_dir / filename

        if settings.mock_mode:
            # Create a placeholder PNG so the path resolves
            try:
                from PIL import Image  # type: ignore
                img = Image.new("RGB", (1920, 1080), color=(20, 24, 32))
                img.save(path)
            except Exception:
                path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"path": str(path), "simulated": True},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        try:
            import pyautogui  # type: ignore
            region = args.get("region")
            img = pyautogui.screenshot(region=tuple(region.values()) if region else None)
            img.save(path)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"path": str(path)},
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
class ScreenOcrTool(Tool):
    name = "screen.ocr"
    description = "Run OCR on a screenshot or the current screen. Returns text + bounding boxes."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 15_000
    input_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string"},
            "language": {"type": "string", "default": "eng"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        language = args.get("language", "eng")

        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={
                    "simulated": True,
                    "text": "",
                    "confidence": 0.0,
                    "bounding_boxes": [],
                },
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            image_path = args.get("image_path")
            img = Image.open(image_path) if image_path else None
            if img is None:
                import pyautogui  # type: ignore
                img = pyautogui.screenshot()

            text = pytesseract.image_to_string(img, lang=language)
            data = pytesseract.image_to_data(img, lang=language, output_type=pytesseract.Output.DICT)
            boxes = [
                {"text": data["text"][i], "x": data["left"][i], "y": data["top"][i],
                 "width": data["width"][i], "height": data["height"][i],
                 "confidence": float(data["conf"][i]) / 100.0}
                for i in range(len(data["text"]))
                if int(data["conf"][i]) > 0 and data["text"][i].strip()
            ]
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"text": text, "bounding_boxes": boxes},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

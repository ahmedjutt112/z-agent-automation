"""Tests for the ToolRegistry and the registered tools (mock mode only).

The autouse ``mock_settings`` fixture in conftest.py ensures
``settings.mock_mode=True`` so no real mouse/keyboard/browser I/O happens.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from automation_service.engine.tool_registry import tool_registry
from automation_service.models import ActionResult, StepStatus


# ---------------------------------------------------------------------------
# Discovery / registration
# ---------------------------------------------------------------------------


def test_registry_has_mouse_tools() -> None:
    """After discover(), the three mouse tools are registered."""
    names = {t.name for t in tool_registry.all()}
    assert {"mouse.click", "mouse.move", "mouse.scroll"} <= names


def test_registry_has_keyboard_tools() -> None:
    names = {t.name for t in tool_registry.all()}
    assert {"keyboard.type", "keyboard.hotkey"} <= names


def test_registry_has_screen_tools() -> None:
    names = {t.name for t in tool_registry.all()}
    assert {"screen.capture", "screen.ocr"} <= names


def test_registry_has_file_tools() -> None:
    names = {t.name for t in tool_registry.all()}
    assert {"file.read", "file.write", "file.move", "file.rename", "file.list"} <= names


def test_registry_has_app_tools() -> None:
    names = {t.name for t in tool_registry.all()}
    assert {"app.launch", "window.list", "process.list"} <= names


def test_registry_has_browser_tools() -> None:
    names = {t.name for t in tool_registry.all()}
    assert {
        "browser.open",
        "browser.navigate",
        "browser.click",
        "browser.type",
        "browser.extract",
    } <= names


def test_registry_total_count() -> None:
    """Master prompt §8 implies ~18+ tools. We expect at least 18 after discover."""
    assert len(tool_registry.all()) >= 18


# ---------------------------------------------------------------------------
# ToolSpec shape
# ---------------------------------------------------------------------------


def test_tool_spec_fields() -> None:
    """Every registered ToolSpec must have the required §8 fields."""
    required = {
        "name",
        "description",
        "input_schema",
        "permission_level",
        "risk_level",
        "timeout_ms",
    }
    for tool in tool_registry.all():
        spec = tool.spec().model_dump()
        missing = required - set(spec.keys())
        assert not missing, f"tool {tool.name!r} missing fields: {missing}"
        # input_schema must be a JSON-Schema-shaped dict
        assert isinstance(spec["input_schema"], dict)
        assert "type" in spec["input_schema"]
        assert spec["timeout_ms"] >= 100


# ---------------------------------------------------------------------------
# Mock-mode execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mouse_click_mock() -> None:
    """mouse.click in mock mode returns status=completed and a simulated flag."""
    tool = tool_registry.get("mouse.click")
    assert tool is not None
    res = await tool.execute({"x": 100, "y": 200, "button": "left"})
    assert res.status == StepStatus.COMPLETED
    assert res.tool == "mouse.click"
    assert res.output["simulated"] is True
    assert res.output["x"] == 100
    assert res.output["y"] == 200
    assert res.output["button"] == "left"


@pytest.mark.asyncio
async def test_keyboard_type_mock() -> None:
    """keyboard.type returns completed and echoes the typed text."""
    tool = tool_registry.get("keyboard.type")
    assert tool is not None
    res = await tool.execute({"text": "hello world"})
    assert res.status == StepStatus.COMPLETED
    assert res.output["simulated"] is True
    assert res.output["text"] == "hello world"
    assert res.output["length"] == 11


@pytest.mark.asyncio
async def test_screen_capture_mock(tmp_screenshots_dir: Path) -> None:
    """screen.capture writes a file under screenshots_dir and returns its path."""
    tool = tool_registry.get("screen.capture")
    assert tool is not None
    res = await tool.execute({"filename": "test_capture.png"})
    assert res.status == StepStatus.COMPLETED
    out_path = Path(res.output["path"])
    assert out_path.parent == tmp_screenshots_dir
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert res.output["simulated"] is True


# ---------------------------------------------------------------------------
# File security (master prompt §55)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_security_blocked_path() -> None:
    """file.read on /etc/passwd raises PermissionError (blocked path)."""
    tool = tool_registry.get("file.read")
    assert tool is not None
    res = await tool.execute({"path": "/etc/passwd"})
    # The tool catches exceptions and returns a FAILED result.
    assert res.status == StepStatus.FAILED
    assert res.error is not None
    assert "blocked" in res.error.lower() or "denied" in res.error.lower()


@pytest.mark.asyncio
async def test_file_security_allowed_path(tmp_path: Path) -> None:
    """file.write to a path under an allowed root succeeds.

    The allowed-roots list (per files.py: ALLOWED_ROOTS) includes the
    project's ``download/`` directory, so we write there.
    """
    from automation_service.config import settings

    # settings.screenshots_dir is already redirected by tmp_screenshots_dir,
    # but download/ is the canonical allowed root. Use settings.project_root
    # to construct a path that survives _validate_path's allowed-root check.
    target = settings.project_root / "download" / "test_output.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        tool = tool_registry.get("file.write")
        assert tool is not None
        res = await tool.execute({"path": str(target), "content": "hello"})
        assert res.status == StepStatus.COMPLETED
        assert target.exists()
        assert target.read_text() == "hello"
    finally:
        if target.exists():
            target.unlink()


@pytest.mark.asyncio
async def test_file_read_after_write(tmp_path: Path) -> None:
    """Round-trip: file.write then file.read in an allowed directory."""
    from automation_service.config import settings

    target = settings.project_root / "download" / "round_trip.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        w = tool_registry.get("file.write")
        r = tool_registry.get("file.read")
        assert w and r
        w_res = await w.execute({"path": str(target), "content": "round trip!"})
        assert w_res.status == StepStatus.COMPLETED
        r_res = await r.execute({"path": str(target)})
        assert r_res.status == StepStatus.COMPLETED
        assert r_res.output["text"] == "round trip!"
    finally:
        if target.exists():
            target.unlink()

"""Browser tools — master prompt §16 (Playwright), §17 (browser agent).

Mock-mode safe: returns simulated results. Real mode requires `playwright`
to be installed and `playwright install chromium` to have been run.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from ..engine.tool_registry import register_tool, Tool
from ..models import ActionResult, StepStatus
from ..config import settings


# ---------------------------------------------------------------------------
# Browser session manager — master prompt §16
# ---------------------------------------------------------------------------


class BrowserSessionManager:
    """Lazy-initialize Playwright. Each session has its own context for isolation."""

    def __init__(self) -> None:
        self._playwright = None
        self._browsers: dict[str, Any] = {}

    async def get_or_create(self, session_id: str, browser: str = "chromium"):
        if settings.mock_mode:
            return None  # tools handle mock case
        if self._playwright is None:
            from playwright.async_api import async_playwright  # type: ignore
            self._playwright = await async_playwright().start()
        if session_id not in self._browsers:
            launcher = getattr(self._playwright, browser)
            self._browsers[session_id] = await launcher.launch(headless=False)
        return self._browsers[session_id]

    async def close_all(self) -> None:
        for b in self._browsers.values():
            try:
                await b.close()
            except Exception:
                pass
        self._browsers.clear()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


browser_sessions = BrowserSessionManager()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool
class BrowserOpenTool(Tool):
    name = "browser.open"
    description = "Open a browser session."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 15_000
    input_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "default": "default"},
            "browser": {"type": "string", "enum": ["chromium", "firefox", "webkit"], "default": "chromium"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        session_id = args.get("session_id", "default")
        browser = args.get("browser", "chromium")
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "session_id": session_id, "browser": browser},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            br = await browser_sessions.get_or_create(session_id, browser)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"session_id": session_id, "browser": browser},
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
class BrowserNavigateTool(Tool):
    name = "browser.navigate"
    description = "Navigate the browser session to a URL."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 30_000
    input_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "default": "default"},
            "url": {"type": "string"},
        },
        "required": ["url"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        url = args["url"]
        session_id = args.get("session_id", "default")
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "url": url, "session_id": session_id},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            br = await browser_sessions.get_or_create(session_id)
            page = await br.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"url": url, "title": await page.title()},
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
class BrowserClickTool(Tool):
    name = "browser.click"
    description = "Click an element by CSS selector."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 10_000
    input_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "default": "default"},
            "selector": {"type": "string"},
        },
        "required": ["selector"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        selector = args["selector"]
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "selector": selector},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            br = await browser_sessions.get_or_create(args.get("session_id", "default"))
            page = br.pages[-1] if br.pages else await br.new_page()
            await page.click(selector, timeout=8000)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"selector": selector},
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
class BrowserTypeTool(Tool):
    name = "browser.type"
    description = "Type text into an element matched by CSS selector."
    permission_level = "allow_once"
    risk_level = "medium"
    timeout_ms = 10_000
    input_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "default": "default"},
            "selector": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["selector", "text"],
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "selector": args["selector"], "text": args["text"]},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            br = await browser_sessions.get_or_create(args.get("session_id", "default"))
            page = br.pages[-1] if br.pages else await br.new_page()
            await page.fill(args["selector"], args["text"], timeout=8000)
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"selector": args["selector"], "length": len(args["text"])},
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
class BrowserExtractTool(Tool):
    name = "browser.extract"
    description = "Extract text content from elements matching a CSS selector."
    permission_level = "allow_once"
    risk_level = "low"
    timeout_ms = 10_000
    input_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "default": "default"},
            "selector": {"type": "string", "default": "body"},
        },
    }

    async def execute(self, args: dict[str, Any]) -> ActionResult:
        start = datetime.now(timezone.utc)
        if settings.mock_mode:
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"simulated": True, "text": "", "selector": args.get("selector", "body")},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        try:
            br = await browser_sessions.get_or_create(args.get("session_id", "default"))
            page = br.pages[-1] if br.pages else await br.new_page()
            text = await page.inner_text(args.get("selector", "body"))
            return ActionResult(
                tool=self.name,
                status=StepStatus.COMPLETED,
                output={"text": text[:5000], "selector": args.get("selector", "body")},
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )
        except Exception as exc:
            return ActionResult(
                tool=self.name, status=StepStatus.FAILED, error=str(exc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=int((datetime.now(timezone.utc) - start).total_seconds() * 1000),
            )

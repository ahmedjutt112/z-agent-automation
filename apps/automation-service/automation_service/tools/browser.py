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
    """Lazy-initialize Playwright. Each session has its own context for isolation.

    Master prompt §49 (multi-profile support) — sessions are keyed by
    ``(profile_id, session_id)`` so two profiles can each have a session
    with the same ``session_id`` without colliding. When ``profile_id`` is
    ``None`` we use the sentinel ``_GLOBAL_PROFILE`` so existing callers
    that don't pass a profile keep working unchanged.
    """

    # Sentinel substituted for None profile_ids (mirrors permission_engine).
    _GLOBAL_PROFILE = "_global"

    def __init__(self) -> None:
        self._playwright = None
        # Keys are (profile_key, session_id) tuples so the same session_id
        # can exist independently under different profiles.
        self._browsers: dict[tuple[str, str], Any] = {}

    @classmethod
    def _profile_key(cls, profile_id: Optional[str]) -> str:
        return profile_id if profile_id is not None else cls._GLOBAL_PROFILE

    async def get_or_create(
        self,
        session_id: str,
        browser: str = "chromium",
        profile_id: Optional[str] = None,
    ):
        """Get an existing browser for ``session_id`` (under ``profile_id``)
        or launch a fresh one.

        Records the BrowserSession row in the DB (best-effort) when a new
        session is created, including the ``profile_id`` so profile-scoped
        queries against ``browser_sessions`` work.
        """
        if settings.mock_mode:
            return None  # tools handle mock case
        if self._playwright is None:
            from playwright.async_api import async_playwright  # type: ignore
            self._playwright = await async_playwright().start()

        profile_key = self._profile_key(profile_id)
        key = (profile_key, session_id)
        if key not in self._browsers:
            launcher = getattr(self._playwright, browser)
            self._browsers[key] = await launcher.launch(headless=False)
            # Best-effort DB row so profile-scoped queries have data.
            try:
                self._record_session_row(session_id, browser, profile_id)
            except Exception:
                pass  # DB might be unavailable in mock mode — never block launch
        return self._browsers[key]

    async def close_all(self, profile_id: Optional[str] = None) -> None:
        """Close browser sessions.

        If ``profile_id`` is provided, only sessions for that profile are
        closed (and the global sessions, by default — pass an explicit
        ``profile_id`` to scope). If ``profile_id`` is ``None`` (default),
        every session is closed (existing behaviour).
        """
        if profile_id is None:
            # Close everything (original behaviour).
            for b in self._browsers.values():
                try:
                    await b.close()
                except Exception:
                    pass
            self._browsers.clear()
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            return

        # Profile-scoped close — only close sessions under that profile key.
        profile_key = self._profile_key(profile_id)
        to_close = [k for k in self._browsers if k[0] == profile_key]
        for k in to_close:
            try:
                await self._browsers[k].close()
            except Exception:
                pass
            del self._browsers[k]
        # If no sessions remain, shut down the playwright instance too.
        if not self._browsers and self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ------------------------------------------------------------------
    # DB row recording (best-effort; mock mode skips)
    # ------------------------------------------------------------------

    @staticmethod
    def _record_session_row(session_id: str, browser: str, profile_id: Optional[str]) -> None:
        """Insert a BrowserSession row if a DB is available.

        Failure here is non-fatal — the in-memory ``_browsers`` dict is
        the source of truth for active sessions; the DB row exists only so
        profile-scoped queries have something to return.
        """
        try:
            from database.base import SessionLocal
            from database.models.schema import BrowserSession
        except ImportError:
            return
        try:
            with SessionLocal() as session:
                existing = (
                    session.query(BrowserSession)
                    .filter(BrowserSession.session_id == session_id)
                    .filter(BrowserSession.profile_id == (profile_id if profile_id else None))
                    .first()
                )
                if existing is not None:
                    return
                row = BrowserSession(
                    session_id=session_id,
                    profile_id=profile_id,
                    browser_type=browser,
                    is_persistent=False,
                    metadata_json={},
                )
                session.add(row)
                session.commit()
        except Exception:
            # Swallow — DB might not exist in mock mode.
            pass


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

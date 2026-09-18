"""Browser session manager FastAPI router — master prompt §16 (Playwright),
§17 (browser agent).

Mounted under ``/browser`` in main.py. Endpoints:

* ``GET    /browser/sessions``            — list active browser sessions
* ``POST   /browser/session``             — create a new session
* ``DELETE /browser/session/{session_id}`` — close a session
* ``POST   /browser/session/{session_id}/navigate``  — go to a URL
* ``POST   /browser/session/{session_id}/click``      — click a selector
* ``POST   /browser/session/{session_id}/type``       — type into a selector
* ``POST   /browser/session/{session_id}/extract``     — extract text
* ``POST   /browser/session/{session_id}/screenshot``  — capture page

All routes require the IPC bearer token. In mock mode the underlying
:mclass:`automation_service.tools.browser.BrowserSessionManager` returns
``None`` for every session — the route layer still records the session in
the in-memory registry so the UI's session list and the per-session
action endpoints work without a real Playwright install.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.tool_registry import tool_registry
from ..models import ActionRequest


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency — lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# In-memory session registry (mock-mode friendly)
# ---------------------------------------------------------------------------


class _SessionRecord(BaseModel):
    """One row in the active-session registry."""

    session_id: str
    browser: str = "chromium"
    headless: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    current_url: Optional[str] = None
    title: Optional[str] = None
    mock_mode: bool = False


# Module-level store. In a multi-worker deployment this would live in a
# shared cache (Redis) — but master prompt §5 binds the service to a single
# localhost process so an in-process dict is correct.
_sessions: dict[str, _SessionRecord] = {}


def _record_or_404(session_id: str) -> _SessionRecord:
    rec = _sessions.get(session_id)
    if rec is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"browser session '{session_id}' not found",
        )
    return rec


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """Body of ``POST /browser/session``."""

    browser: str = Field(default="chromium", pattern="^(chromium|firefox|webkit)$")
    headless: bool = True
    session_id: Optional[str] = None  # auto-generated when omitted


class NavigateRequest(BaseModel):
    url: str


class ClickRequest(BaseModel):
    selector: str


class TypeRequest(BaseModel):
    selector: str
    text: str


class ExtractRequest(BaseModel):
    selector: str = "body"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_list_sessions() -> dict[str, Any]:
    """Return every active browser session."""
    return {
        "sessions": [s.model_dump(mode="json") for s in _sessions.values()],
        "count": len(_sessions),
        "mock_mode": bool(settings.mock_mode),
    }


@router.post(
    "/session",
    dependencies=[Depends(_verify_ipc_token)],
    status_code=status.HTTP_201_CREATED,
    tags=["browser"],
)
async def browser_create_session(req: CreateSessionRequest) -> dict[str, Any]:
    """Open a new browser session.

    In mock mode the underlying Playwright instance is never started —
    we just record the session metadata so the UI's session list works.
    """
    from uuid import uuid4

    session_id = req.session_id or f"sess_{uuid4().hex[:8]}"
    if session_id in _sessions:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"session_id '{session_id}' already exists — pick a unique id",
        )
    rec = _SessionRecord(
        session_id=session_id,
        browser=req.browser,
        headless=req.headless,
        mock_mode=bool(settings.mock_mode),
    )
    _sessions[session_id] = rec

    if not settings.mock_mode:
        # Real mode: ask the BrowserSessionManager to actually launch.
        from ..tools.browser import browser_sessions

        try:
            await browser_sessions.get_or_create(
                session_id, browser=req.browser, profile_id=None
            )
        except Exception as exc:
            # Don't crash — the session record is still useful for the UI.
            _sessions[session_id].title = f"launch failed: {exc}"

    return {"session": rec.model_dump(mode="json"), "mock_mode": bool(settings.mock_mode)}


@router.delete(
    "/session/{session_id}",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_close_session(session_id: str) -> dict[str, Any]:
    """Close a browser session. Returns 404 when unknown."""
    rec = _record_or_404(session_id)

    if not settings.mock_mode:
        from ..tools.browser import browser_sessions

        try:
            await browser_sessions.close_all(profile_id=None)
        except Exception:
            pass  # best-effort — the registry is the source of truth

    del _sessions[session_id]
    return {"session_id": session_id, "closed": True, "mock_mode": bool(settings.mock_mode)}


@router.post(
    "/session/{session_id}/navigate",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_navigate(session_id: str, req: NavigateRequest) -> dict[str, Any]:
    """Navigate a session to ``req.url``."""
    rec = _record_or_404(session_id)
    tool = tool_registry.get("browser.navigate")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "browser.navigate tool not registered",
        )
    result = await tool.execute({"session_id": session_id, "url": req.url})
    rec.current_url = req.url
    if isinstance(result.output, dict):
        rec.title = result.output.get("title", rec.title)
    return {
        "session_id": session_id,
        "url": req.url,
        "title": rec.title,
        "mock_mode": bool(result.output.get("simulated", False)) if isinstance(result.output, dict) else False,
        "result": result.model_dump(mode="json"),
    }


@router.post(
    "/session/{session_id}/click",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_click(session_id: str, req: ClickRequest) -> dict[str, Any]:
    """Click an element by CSS selector."""
    _record_or_404(session_id)
    tool = tool_registry.get("browser.click")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "browser.click tool not registered",
        )
    result = await tool.execute({"session_id": session_id, "selector": req.selector})
    return {
        "session_id": session_id,
        "selector": req.selector,
        "mock_mode": bool(result.output.get("simulated", False)) if isinstance(result.output, dict) else False,
        "result": result.model_dump(mode="json"),
    }


@router.post(
    "/session/{session_id}/type",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_type(session_id: str, req: TypeRequest) -> dict[str, Any]:
    """Type text into an element matched by CSS selector."""
    _record_or_404(session_id)
    tool = tool_registry.get("browser.type")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "browser.type tool not registered",
        )
    result = await tool.execute(
        {
            "session_id": session_id,
            "selector": req.selector,
            "text": req.text,
        }
    )
    return {
        "session_id": session_id,
        "selector": req.selector,
        "length": len(req.text),
        "mock_mode": bool(result.output.get("simulated", False)) if isinstance(result.output, dict) else False,
        "result": result.model_dump(mode="json"),
    }


@router.post(
    "/session/{session_id}/extract",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_extract(session_id: str, req: ExtractRequest) -> dict[str, Any]:
    """Extract text from elements matching the selector."""
    _record_or_404(session_id)
    tool = tool_registry.get("browser.extract")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "browser.extract tool not registered",
        )
    result = await tool.execute(
        {"session_id": session_id, "selector": req.selector}
    )
    text = ""
    if isinstance(result.output, dict):
        text = result.output.get("text", "")
    return {
        "session_id": session_id,
        "selector": req.selector,
        "text": text,
        "mock_mode": bool(result.output.get("simulated", False)) if isinstance(result.output, dict) else False,
        "result": result.model_dump(mode="json"),
    }


@router.post(
    "/session/{session_id}/screenshot",
    dependencies=[Depends(_verify_ipc_token)],
    tags=["browser"],
)
async def browser_screenshot(session_id: str) -> dict[str, Any]:
    """Capture a screenshot of the session's current page."""
    _record_or_404(session_id)
    tool = tool_registry.get("screen.capture")
    if tool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "screen.capture tool not registered",
        )
    result = await tool.execute({"session_id": session_id})
    return {
        "session_id": session_id,
        "mock_mode": bool(result.output.get("simulated", False)) if isinstance(result.output, dict) else False,
        "result": result.model_dump(mode="json"),
    }

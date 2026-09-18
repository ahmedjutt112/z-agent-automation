"""Self-healing target resolver — master prompt section 40.

When a workflow step fails because a UI element moved / changed / no longer
matches the original selector, the resolver walks the cascade from §40:

::

    DOM selector
        ↓
    Accessibility selector
        ↓
    Text search
        ↓
    OCR
        ↓
    Image recognition
        ↓
    AI visual interpretation
        ↓
    Pause + ask user   ← if all of the above fail

Each strategy returns a ``{"success": bool, "strategy": str, ...}`` dict.
The resolver returns the first success; if none succeed it returns
``{"success": False, "reason": "ask_user"}``.

AI visual results below ``settings.min_vision_confidence`` (default 0.85 per
master prompt section 86) are treated as a failure of that strategy and
escalate to ``ask_user`` rather than guessing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from ..config import settings


# Strategy names in cascade order (master prompt §40).
STRATEGY_DOM = "dom_selector"
STRATEGY_ACCESSIBILITY = "accessibility_selector"
STRATEGY_TEXT = "text_search"
STRATEGY_OCR = "ocr"
STRATEGY_IMAGE = "image_recognition"
STRATEGY_AI_VISUAL = "ai_visual"

_STRATEGY_ORDER: list[str] = [
    STRATEGY_DOM,
    STRATEGY_ACCESSIBILITY,
    STRATEGY_TEXT,
    STRATEGY_OCR,
    STRATEGY_IMAGE,
    STRATEGY_AI_VISUAL,
]

ASK_USER_RESULT: dict[str, Any] = {"success": False, "reason": "ask_user"}


class SelfHealingResolver:
    """Resolve a UI target through the §40 cascade.

    A "target" is a dict describing the element to interact with, e.g.::

        {"selector": "button#submit", "text": "Submit", "image": "submit.png"}

    The resolver tries each strategy in order. The first strategy to return
    a high-confidence hit wins. If all strategies fail (or return below the
    confidence threshold) the resolver returns the ``ask_user`` sentinel so
    the workflow executor can pause and surface a confirmation prompt.

    All strategy handlers are async and accept ``(target, ctx)``. They are
    registered in a dict so plugins can add new strategies (§53).
    """

    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(self, confidence_threshold: Optional[float] = None) -> None:
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else float(settings.min_vision_confidence)
        )
        self._strategies: dict[str, Callable[[dict, dict], Awaitable[dict]]] = {
            STRATEGY_DOM: self._strategy_dom,
            STRATEGY_ACCESSIBILITY: self._strategy_accessibility,
            STRATEGY_TEXT: self._strategy_text,
            STRATEGY_OCR: self._strategy_ocr,
            STRATEGY_IMAGE: self._strategy_image,
            STRATEGY_AI_VISUAL: self._strategy_ai_visual,
        }
        # Per-strategy timeout, overridable via ``set_timeout``.
        self._timeouts: dict[str, float] = {
            name: self.DEFAULT_TIMEOUT_SECONDS for name in self._strategies
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_target(self, target: dict, context: Optional[dict] = None) -> dict:
        """Try each strategy in §40 order. Return first success.

        If every strategy fails, return ``{"success": False, "reason": "ask_user"}``.
        """
        ctx = context or {}
        if not isinstance(target, dict) or not target:
            return {**ASK_USER_RESULT, "reason": "empty_target"}

        for name in _STRATEGY_ORDER:
            handler = self._strategies.get(name)
            if handler is None:
                continue
            timeout = self._timeouts.get(name, self.DEFAULT_TIMEOUT_SECONDS)
            try:
                result = await asyncio.wait_for(handler(target, ctx), timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug("self-healing strategy '{}' timed out after {}s", name, timeout)
                continue
            except Exception as exc:
                logger.debug("self-healing strategy '{}' raised: {}", name, exc)
                continue

            if self._is_success(result):
                logger.info(
                    "self-healing resolved target via strategy='{}' confidence={}",
                    name,
                    result.get("confidence"),
                )
                return result

        # All strategies exhausted — escalate to the user.
        return {**ASK_USER_RESULT}

    def register_strategy(
        self, name: str, handler: Callable[[dict, dict], Awaitable[dict]]
    ) -> None:
        """Register a new (or override an existing) strategy.

        Plugins use this hook to inject their own UI discovery mechanism
        (e.g. a custom AT-SPI bridge). Strategies added this way are NOT
        automatically placed in the cascade — callers should also call
        :meth:`prepend_strategy` if they want their strategy tried first.
        """
        self._strategies[name] = handler
        self._timeouts.setdefault(name, self.DEFAULT_TIMEOUT_SECONDS)

    def set_timeout(self, strategy_name: str, seconds: float) -> None:
        self._timeouts[strategy_name] = max(0.1, float(seconds))

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    async def _strategy_dom(self, target: dict, ctx: dict) -> dict:
        """Use ``browser.click`` with the CSS selector.

        Returns the resolved selector + bounding box if the element is
        present in the active browser page.
        """
        selector = target.get("selector") or target.get("dom_selector")
        if not selector:
            return {"success": False, "strategy": STRATEGY_DOM, "reason": "no_selector"}
        if settings.mock_mode:
            # Mock: pretend the selector resolved. The executor will re-run
            # the step with these args; downstream tools are also mock so
            # the workflow can complete end-to-end in tests.
            return {
                "success": True,
                "strategy": STRATEGY_DOM,
                "selector": selector,
                "bounding_box": {"x": 100, "y": 100, "width": 80, "height": 30},
                "confidence": 1.0,
                "resolved_target": {"selector": selector},
            }
        try:
            from ..tools.browser import browser_sessions  # type: ignore

            session_id = target.get("session_id", "default")
            br = await browser_sessions.get_or_create(session_id)
            page = br.pages[-1] if br.pages else await br.new_page()
            handle = await page.query_selector(selector)
            if handle is None:
                return {"success": False, "strategy": STRATEGY_DOM, "reason": "not_found"}
            box = await handle.bounding_box()
            return {
                "success": True,
                "strategy": STRATEGY_DOM,
                "selector": selector,
                "bounding_box": box,
                "confidence": 1.0,
                "resolved_target": {"selector": selector},
            }
        except Exception as exc:
            return {"success": False, "strategy": STRATEGY_DOM, "reason": str(exc)}

    async def _strategy_accessibility(self, target: dict, ctx: dict) -> dict:
        """Use pywinauto (Windows) or AT-SPI (Linux) to find the element.

        Accessibility selectors are more robust than DOM because they
        survive CSS refactors — but they only exist for native apps and
        Electron-with-a11y. We attempt a discovery and fall through to the
        next strategy if the platform SDK isn't available.
        """
        a11y = target.get("accessibility_selector") or target.get("automation_id")
        if not a11y:
            return {
                "success": False,
                "strategy": STRATEGY_ACCESSIBILITY,
                "reason": "no_accessibility_selector",
            }
        if settings.mock_mode:
            return {
                "success": True,
                "strategy": STRATEGY_ACCESSIBILITY,
                "automation_id": a11y,
                "bounding_box": {"x": 100, "y": 100, "width": 80, "height": 30},
                "confidence": 0.95,
                "resolved_target": {"accessibility_selector": a11y},
            }
        try:
            import sys

            if sys.platform == "win32":
                import pywinauto  # type: ignore

                app = pywinauto.Application(backend="uia").connect(
                    title_re=target.get("window_title", ".*")
                )
                elem = app.window(best_match=a11y)
                rect = elem.rectangle()
                return {
                    "success": True,
                    "strategy": STRATEGY_ACCESSIBILITY,
                    "automation_id": a11y,
                    "bounding_box": {
                        "x": rect.left,
                        "y": rect.top,
                        "width": rect.width(),
                        "height": rect.height(),
                    },
                    "confidence": 0.95,
                    "resolved_target": {"accessibility_selector": a11y},
                }
        except Exception as exc:
            return {
                "success": False,
                "strategy": STRATEGY_ACCESSIBILITY,
                "reason": str(exc),
            }
        return {"success": False, "strategy": STRATEGY_ACCESSIBILITY, "reason": "unsupported_platform"}

    async def _strategy_text(self, target: dict, ctx: dict) -> dict:
        """Screen-OCR + locate the desired text on screen.

        This strategy is shared with :py:meth:`_strategy_ocr` — text_search
        is the higher-level "find the label" step, while OCR is the lower-
        level "find any text in this region" fallback.
        """
        needle = target.get("text") or target.get("label")
        if not needle:
            return {"success": False, "strategy": STRATEGY_TEXT, "reason": "no_text"}
        ocr_result = await self._run_ocr()
        if not ocr_result.get("success"):
            return ocr_result  # already tagged with strategy
        for box in ocr_result.get("bounding_boxes", []):
            if needle.lower() in (box.get("text") or "").lower():
                return {
                    "success": True,
                    "strategy": STRATEGY_TEXT,
                    "text": needle,
                    "bounding_box": {
                        "x": box["x"],
                        "y": box["y"],
                        "width": box.get("width", 0),
                        "height": box.get("height", 0),
                    },
                    "center": {
                        "x": box["x"] + box.get("width", 0) // 2,
                        "y": box["y"] + box.get("height", 0) // 2,
                    },
                    "confidence": float(box.get("confidence", 0.9)),
                    "resolved_target": {"click_x": box["x"], "click_y": box["y"]},
                }
        return {"success": False, "strategy": STRATEGY_TEXT, "reason": "text_not_found"}

    async def _strategy_ocr(self, target: dict, ctx: dict) -> dict:
        """Run OCR on the current screen and return the first matching text."""
        ocr_result = await self._run_ocr()
        if not ocr_result.get("success"):
            return ocr_result
        boxes = ocr_result.get("bounding_boxes", [])
        if not boxes:
            return {"success": False, "strategy": STRATEGY_OCR, "reason": "no_text_found"}
        # No specific needle — return the first box.
        first = boxes[0]
        return {
            "success": True,
            "strategy": STRATEGY_OCR,
            "text": first.get("text", ""),
            "bounding_box": {
                "x": first["x"],
                "y": first["y"],
                "width": first.get("width", 0),
                "height": first.get("height", 0),
            },
            "confidence": float(first.get("confidence", 0.5)),
            "resolved_target": {"click_x": first["x"], "click_y": first["y"]},
        }

    async def _strategy_image(self, target: dict, ctx: dict) -> dict:
        """Use pyautogui.locateOnScreen to find an image template."""
        image_path = target.get("image") or target.get("image_path")
        if not image_path:
            return {"success": False, "strategy": STRATEGY_IMAGE, "reason": "no_image"}
        if settings.mock_mode:
            return {
                "success": True,
                "strategy": STRATEGY_IMAGE,
                "image": image_path,
                "bounding_box": {"x": 100, "y": 100, "width": 50, "height": 50},
                "confidence": 0.9,
                "resolved_target": {"click_x": 125, "click_y": 125},
            }
        try:
            import pyautogui  # type: ignore

            loc = pyautogui.locateOnScreen(image_path, confidence=0.8)
            if loc is None:
                return {"success": False, "strategy": STRATEGY_IMAGE, "reason": "not_found"}
            center = pyautogui.center(loc)
            return {
                "success": True,
                "strategy": STRATEGY_IMAGE,
                "image": image_path,
                "bounding_box": {
                    "x": loc.left,
                    "y": loc.top,
                    "width": loc.width,
                    "height": loc.height,
                },
                "center": {"x": center.x, "y": center.y},
                "confidence": 0.9,
                "resolved_target": {"click_x": center.x, "click_y": center.y},
            }
        except Exception as exc:
            return {"success": False, "strategy": STRATEGY_IMAGE, "reason": str(exc)}

    async def _strategy_ai_visual(self, target: dict, ctx: dict) -> dict:
        """Send a screenshot to a vision model and ask for a bounding box.

        Per master prompt §86 we require confidence >= the configured
        threshold (default 0.85); below that we return ``success=False``
        so the resolver escalates to ``ask_user``.
        """
        if settings.mock_mode:
            # Mock: simulate a low-confidence AI guess so the resolver
            # escalates to ask_user — keeps the engine from "guessing".
            return {
                "success": False,
                "strategy": STRATEGY_AI_VISUAL,
                "reason": "mock_low_confidence",
                "confidence": 0.5,
            }
        try:
            from ..tools.screen import ScreenCaptureTool  # type: ignore
            from ..ai_providers.base import AIProvider, AIProviderConfig, get_provider  # type: ignore

            cap = ScreenCaptureTool()
            shot = await cap.execute({"filename": f"self_heal_{int(__import__('time').time())}.png"})
            if shot.status.value != "completed":
                return {"success": False, "strategy": STRATEGY_AI_VISUAL, "reason": "screenshot_failed"}
            prompt = (
                "Find the UI element described by the user. "
                f"Description: {target.get('text') or target.get('label') or target.get('selector', '')}. "
                "Return ONLY a JSON object {\"x\": int, \"y\": int, \"width\": int, \"height\": int, \"confidence\": float}."
            )
            cfg = AIProviderConfig(
                name=settings.default_ai_provider,
                api_key=__import__("os").getenv("OPENAI_API_KEY") or __import__("os").getenv("ANTHROPIC_API_KEY"),
                model=settings.default_ai_model,
            )
            provider = get_provider(settings.default_ai_provider, cfg)
            response = await provider.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            import json
            import re

            m = re.search(r"\{[\s\S]*\}", response)
            if not m:
                return {"success": False, "strategy": STRATEGY_AI_VISUAL, "reason": "no_json"}
            try:
                box = json.loads(m.group(0))
            except json.JSONDecodeError:
                return {"success": False, "strategy": STRATEGY_AI_VISUAL, "reason": "bad_json"}
            conf = float(box.get("confidence", 0.0))
            if conf < self.confidence_threshold:
                logger.info(
                    "AI visual confidence {} below threshold {} — escalating",
                    conf,
                    self.confidence_threshold,
                )
                return {
                    "success": False,
                    "strategy": STRATEGY_AI_VISUAL,
                    "reason": "below_confidence_threshold",
                    "confidence": conf,
                }
            return {
                "success": True,
                "strategy": STRATEGY_AI_VISUAL,
                "bounding_box": {
                    "x": int(box.get("x", 0)),
                    "y": int(box.get("y", 0)),
                    "width": int(box.get("width", 0)),
                    "height": int(box.get("height", 0)),
                },
                "confidence": conf,
                "resolved_target": {
                    "click_x": int(box.get("x", 0)) + int(box.get("width", 0)) // 2,
                    "click_y": int(box.get("y", 0)) + int(box.get("height", 0)) // 2,
                },
            }
        except Exception as exc:
            return {"success": False, "strategy": STRATEGY_AI_VISUAL, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_success(self, result: dict) -> bool:
        """A result is successful if ``success`` is True AND, when present,
        ``confidence`` is >= the configured threshold.
        """
        if not result.get("success"):
            return False
        conf = result.get("confidence")
        if conf is None:
            return True
        try:
            return float(conf) >= self.confidence_threshold
        except (TypeError, ValueError):
            return True

    async def _run_ocr(self) -> dict:
        """Run screen.ocr via the tool registry (real mode) or return a
        mock result (mock mode).
        """
        if settings.mock_mode:
            return {
                "success": True,
                "strategy": STRATEGY_OCR,
                "text": "",
                "bounding_boxes": [],
            }
        try:
            from ..tools.screen import ScreenOcrTool  # type: ignore

            ocr = ScreenOcrTool()
            res = await ocr.execute({})
            if res.status.value != "completed":
                return {"success": False, "strategy": STRATEGY_OCR, "reason": "ocr_failed"}
            boxes = res.output.get("bounding_boxes", []) if res.output else []
            return {
                "success": True,
                "strategy": STRATEGY_OCR,
                "text": res.output.get("text", "") if res.output else "",
                "bounding_boxes": boxes,
            }
        except Exception as exc:
            return {"success": False, "strategy": STRATEGY_OCR, "reason": str(exc)}


# Module-level singleton — WorkflowExecutor uses this by default.
self_healing_resolver = SelfHealingResolver()

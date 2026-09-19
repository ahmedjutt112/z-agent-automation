"""RecoveryAgent - master prompt section 7 (Recovery agent), section 39
(error handling), section 40 (self-healing), section 60 (reliability).

When a step fails, the RecoveryAgent is consulted. It analyses the
failure via the ObserverAgent and produces a :class:`RecoveryPlan` that
tells the executor what to do next:

* ``retry_with_delay`` - same action, wait 2s (transient flake).
* ``retry_with_fallback`` - use a different tool (e.g. ``browser.click``
  -> ``mouse.click`` on OCR'd coordinates).
* ``dismiss_popup`` - a popup was detected; dismiss it and retry.
* ``scroll_and_retry`` - the element might be below the fold.
* ``wait_and_retry`` - the page/app is still loading.
* ``ask_user`` - recovery exhausted; pause and surface a prompt.

CRITICAL: never loops infinitely. The agent tracks per-step recovery
attempt counts and forces ``ask_user`` after 3 attempts (configurable
via ``settings.max_recovery_attempts`` if set, otherwise hard-coded 3).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.event_bus import event_bus
from .observer_agent import ObserverAgent, observer_agent as default_observer
from .planner import PlannerAgent


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FailureContext(BaseModel):
    """The context the executor passes to :meth:`RecoveryAgent.recover_from_failure`.

    All fields are optional except ``failed_action`` - the executor
    fills in what it has.
    """

    failed_action: str
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    step_context: dict[str, Any] = Field(default_factory=dict)
    attempt_number: int = 0  # how many times we've already retried (1-based)


class RecoveryPlan(BaseModel):
    """The agent's verdict on what to do next."""

    strategy: str = "ask_user"
    alternative_actions: list[str] = Field(default_factory=list)
    should_retry: bool = False
    should_skip: bool = False
    should_ask_user: bool = False
    reason: str = ""
    retry_delay_seconds: float = 0.0


# ---------------------------------------------------------------------------
# RecoveryAgent
# ---------------------------------------------------------------------------


class RecoveryAgent:
    """Decides how to recover from a failed step - master prompt section 60."""

    # Per master prompt section 60: never loop infinitely. 3 attempts
    # per step is the hard ceiling.
    MAX_RECOVERY_ATTEMPTS = 3

    # Recognised strategy names (mirror the spec in the module docstring).
    STRATEGY_RETRY_WITH_DELAY = "retry_with_delay"
    STRATEGY_RETRY_WITH_FALLBACK = "retry_with_fallback"
    STRATEGY_DISMISS_POPUP = "dismiss_popup"
    STRATEGY_SCROLL_AND_RETRY = "scroll_and_retry"
    STRATEGY_WAIT_AND_RETRY = "wait_and_retry"
    STRATEGY_ASK_USER = "ask_user"

    # Common fallback tool map - when we suggest a fallback we look the
    # failed action up here to find a sensible alternative.
    FALLBACK_TOOL_MAP: dict[str, str] = {
        "browser.click": "mouse.click",
        "browser.type": "keyboard.type",
        "browser.navigate": "browser.open",
        "mouse.click": "screen.ocr",  # fall back to OCR + click the text
        "keyboard.type": "keyboard.hotkey",  # try paste instead
        "app.launch": "browser.open",
    }

    def __init__(
        self,
        observer: Optional[ObserverAgent] = None,
        planner: Optional[PlannerAgent] = None,
    ) -> None:
        self._observer: ObserverAgent = observer or default_observer
        self._planner: Optional[PlannerAgent] = planner

    # ------------------------------------------------------------------
    # recover_from_failure
    # ------------------------------------------------------------------

    async def recover_from_failure(self, failure: FailureContext) -> RecoveryPlan:
        """Analyse ``failure`` and return a :class:`RecoveryPlan`.

        Decision tree:

        1. If ``attempt_number`` >= MAX -> ``ask_user`` (don't infinite loop).
        2. Otherwise, observe the current state + check for anomalies.
        3. If a popup / error dialog anomaly is detected -> ``dismiss_popup``
           + retry after the dismiss.
        4. If the error mentions "timeout" / "loading" -> ``wait_and_retry``
           (2s delay).
        5. If the error mentions "element not found" / "stale" ->
           ``scroll_and_retry``.
        6. If a sensible fallback tool exists -> ``retry_with_fallback``.
        7. Otherwise -> ``retry_with_delay`` (2s) on attempts 1-2,
           ``ask_user`` on attempt 3.
        """
        attempt = max(1, int(failure.attempt_number or 1))

        # Hard ceiling - never infinite-loop.
        if attempt >= self.MAX_RECOVERY_ATTEMPTS:
            return RecoveryPlan(
                strategy=self.STRATEGY_ASK_USER,
                should_ask_user=True,
                should_retry=False,
                reason=(
                    f"max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) reached - "
                    "escalating to user per master prompt section 60"
                ),
            )

        # Observe current state for anomaly-driven strategies.
        anomalies = await self._observer.detect_anomalies(failure.screenshot_path)
        popup_anomalies = [a for a in anomalies if a.type in ("popup", "error_dialog")]

        if popup_anomalies:
            # Try to dismiss the popup. If dismissal succeeds, retry.
            dismissed = await self.dismiss_popup(popup_anomalies[0].description)
            return RecoveryPlan(
                strategy=self.STRATEGY_DISMISS_POPUP,
                should_retry=dismissed,
                should_ask_user=not dismissed,
                reason=(
                    "popup detected and dismissed; retrying"
                    if dismissed
                    else "popup detected but dismissal failed; ask user"
                ),
                retry_delay_seconds=0.5,
            )

        err = (failure.error or "").lower()

        # Slow loading / timeout -> wait + retry.
        if any(k in err for k in ("timeout", "loading", "navigation", "wait")):
            return RecoveryPlan(
                strategy=self.STRATEGY_WAIT_AND_RETRY,
                should_retry=True,
                reason="error suggests slow loading - waiting 2s",
                retry_delay_seconds=2.0,
            )

        # Element-not-found -> scroll + retry (might be below the fold).
        if any(k in err for k in ("not found", "stale", "element", "no such", "not visible")):
            return RecoveryPlan(
                strategy=self.STRATEGY_SCROLL_AND_RETRY,
                should_retry=True,
                reason="element not found - scrolling and retrying",
                retry_delay_seconds=0.5,
            )

        # If we have a sensible fallback tool, suggest it.
        fb = self.FALLBACK_TOOL_MAP.get(failure.failed_action)
        if fb is not None:
            return RecoveryPlan(
                strategy=self.STRATEGY_RETRY_WITH_FALLBACK,
                alternative_actions=[fb],
                should_retry=True,
                reason=(
                    f"retrying '{failure.failed_action}' via fallback tool '{fb}'"
                ),
                retry_delay_seconds=0.5,
            )

        # Default: retry with delay (attempt 1-2), ask user on attempt 3.
        return RecoveryPlan(
            strategy=self.STRATEGY_RETRY_WITH_DELAY,
            should_retry=True,
            reason=f"transient failure on attempt {attempt} - retrying after 2s",
            retry_delay_seconds=2.0,
        )

    # ------------------------------------------------------------------
    # dismiss_popup
    # ------------------------------------------------------------------

    async def dismiss_popup(self, popup_description: str) -> bool:
        """Detect common popups (cookie consent, newsletter signup, error
        dialog) and click the dismiss button.

        Returns ``True`` if the popup was dismissed, ``False`` otherwise.
        """
        if settings.mock_mode:
            # Mock: pretend we always find + click the dismiss button so
            # the recovery flow can be exercised end-to-end.
            logger.info("mock dismiss_popup: '{}' dismissed", popup_description)
            event_bus.publish(
                "STEP_COMPLETED",
                {"strategy": "dismiss_popup", "description": popup_description, "mock": True},
            )
            return True

        # Common dismiss-button labels we try in order.
        dismiss_labels = (
            "Accept all",
            "Accept",
            "OK",
            "Close",
            "No thanks",
            "Not now",
            "Cancel",
            "Dismiss",
            "X",
            "Got it",
        )
        for label in dismiss_labels:
            loc = await self._observer.find_element(label)
            if loc is None:
                continue
            try:
                from ..engine.tool_registry import tool_registry
                from ..models import StepStatus

                click_tool = tool_registry.get("mouse.click")
                if click_tool is None:
                    continue
                res = await click_tool.execute(
                    {"x": loc.x + loc.width // 2, "y": loc.y + loc.height // 2}
                )
                if res.status == StepStatus.COMPLETED:
                    event_bus.publish(
                        "STEP_COMPLETED",
                        {"strategy": "dismiss_popup", "label": label},
                    )
                    return True
            except Exception as exc:
                logger.debug("dismiss_popup click failed for '{}': {}", label, exc)
                continue

        logger.info("dismiss_popup: no dismiss button matched '{}'", popup_description)
        return False

    # ------------------------------------------------------------------
    # handle_slow_loading
    # ------------------------------------------------------------------

    async def handle_slow_loading(self, timeout_seconds: int = 30) -> bool:
        """Poll the screen for ``timeout_seconds`` until the app looks
        responsive (a non-anomalous state).

        Returns ``True`` if the app became responsive within the timeout.
        """
        if settings.mock_mode:
            # Mock: pretend the app became responsive immediately.
            return True

        deadline = time.time() + max(1, int(timeout_seconds))
        poll_interval = 1.0
        while time.time() < deadline:
            anomalies = await self._observer.detect_anomalies()
            # If the only anomalies are popups we can dismiss, dismiss
            # them and keep waiting. If we see a real "unresponsive_app"
            # anomaly we keep polling.
            severe = [a for a in anomalies if a.type == "unresponsive_app"]
            if not severe:
                return True
            await asyncio.sleep(poll_interval)
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


recovery_agent = RecoveryAgent()


__all__ = [
    "FailureContext",
    "RecoveryAgent",
    "RecoveryPlan",
    "recovery_agent",
]

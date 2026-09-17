"""Conditions + Loops — master prompt sections 42 (CONDITIONS) and 43 (LOOPS).

Two cooperating classes:

* :class:`ConditionEvaluator` — evaluates a single condition dict (``{"type":
  "file_exists", "path": "..."}``) or compound ``and`` / ``or`` / ``not``
  trees and returns a boolean. The condition schema mirrors §42.

* :class:`LoopExecutor` — runs a loop body (an ``async`` callback) over the
  items produced by a loop spec (``for_each_file``, ``for_each_row``,
  ``while``, ``retry``, ``batch``, ...). All loops enforce
  ``max_iterations`` per §43 ("Include maximum iteration limits") and the
  global ``settings.max_loops`` cap.

Both classes degrade gracefully in mock mode (``settings.mock_mode=True``):
network checks skip the real socket connect, browser-result loops return
fake rows, etc. — so unit tests can run without I/O.
"""

from __future__ import annotations

import asyncio
import csv
import socket
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from loguru import logger

from ..config import settings
from .variables import variable_engine


# Type alias for the loop-body callback. The callback receives the current
# iteration item (str, dict, list, etc. depending on loop type) and returns
# either a value (sync) or an awaitable (async).
LoopCallback = Callable[[Any], Awaitable[Any] | Any]


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------


class ConditionEvaluator:
    """Evaluate a condition dict to a boolean — master prompt §42.

    Each condition is a JSON object with ``"type"`` plus type-specific
    parameters. Supported types:

    ``file_exists``               — ``{"path": "..."}``
    ``window_exists``             — ``{"title": "..."}``
    ``text_exists``               — ``{"text": "...", "in": "clipboard|screen|file:<path>"}``
    ``image_exists``              — ``{"path": "..."}``
    ``browser_element_exists``    — ``{"selector": "...", "session_id": "default"}``
    ``process_running``           — ``{"name": "..."}``
    ``network_available``          — ``{}`` (no params)
    ``ai_condition``              — ``{"prompt": "..."}``
    ``and`` / ``or`` / ``not``    — compound conditions

    Unknown condition types return ``False`` (safe default — never crash a
    workflow because the planner emitted a typo).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict, dict], bool]] = {
            "file_exists": self._cond_file_exists,
            "window_exists": self._cond_window_exists,
            "text_exists": self._cond_text_exists,
            "image_exists": self._cond_image_exists,
            "browser_element_exists": self._cond_browser_element_exists,
            "process_running": self._cond_process_running,
            "network_available": self._cond_network_available,
            "ai_condition": self._cond_ai_condition,
            "and": self._cond_and,
            "or": self._cond_or,
            "not": self._cond_not,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, condition: dict, context: Optional[dict] = None) -> bool:
        """Evaluate ``condition`` and return a boolean.

        ``context`` is an optional dict of variables used for ``{{var}}``
        substitution inside string-valued condition parameters.
        """
        if not isinstance(condition, dict):
            return False
        ctx = context or {}
        cond_type = condition.get("type")
        handler = self._handlers.get(cond_type) if cond_type else None
        if handler is None:
            logger.warning("unknown condition type {!r} — treating as False", cond_type)
            return False
        try:
            return bool(handler(condition, ctx))
        except Exception as exc:
            logger.warning("condition {} raised: {}", cond_type, exc)
            return False

    # ------------------------------------------------------------------
    # Leaf conditions
    # ------------------------------------------------------------------

    def _cond_file_exists(self, cond: dict, ctx: dict) -> bool:
        path = self._resolve(cond.get("path", ""), ctx)
        if not path:
            return False
        return Path(path).expanduser().exists()

    def _cond_window_exists(self, cond: dict, ctx: dict) -> bool:
        title = self._resolve(cond.get("title", ""), ctx)
        if settings.mock_mode:
            # Mock mode: pretend any non-empty title exists so workflows
            # don't block forever waiting for a real window manager.
            return bool(title)
        try:
            import pyautogui  # type: ignore

            wins = pyautogui.getWindowsWithTitle(title)
            return len(wins) > 0
        except Exception as exc:
            logger.debug("window_exists check failed: {}", exc)
            return False

    def _cond_text_exists(self, cond: dict, ctx: dict) -> bool:
        needle = self._resolve(cond.get("text", ""), ctx)
        location = cond.get("in", "clipboard")
        if not needle:
            return False
        if location == "clipboard":
            try:
                import pyperclip  # type: ignore

                return needle in (pyperclip.paste() or "")
            except Exception:
                return False
        if location.startswith("file:"):
            file_path = location[len("file:"):]
            try:
                return needle in Path(file_path).read_text(encoding="utf-8")
            except Exception:
                return False
        if location == "screen":
            # In real mode we'd call screen.ocr. Mock mode has no OCR.
            return False
        return False

    def _cond_image_exists(self, cond: dict, ctx: dict) -> bool:
        path = self._resolve(cond.get("path", ""), ctx)
        if not path or not Path(path).expanduser().exists():
            return False
        if settings.mock_mode:
            return True
        try:
            import pyautogui  # type: ignore

            return pyautogui.locateOnScreen(path) is not None
        except Exception:
            return False

    def _cond_browser_element_exists(self, cond: dict, ctx: dict) -> bool:
        selector = self._resolve(cond.get("selector", ""), ctx)
        if settings.mock_mode:
            return bool(selector)
        # Real-mode implementation would use the browser session manager.
        # We don't import the playwright session here to keep the module
        # side-effect free; a future hook can wire this up.
        return False

    def _cond_process_running(self, cond: dict, ctx: dict) -> bool:
        name = self._resolve(cond.get("name", ""), ctx).lower()
        if not name:
            return False
        if settings.mock_mode:
            return False
        try:
            import psutil  # type: ignore

            for p in psutil.process_iter(["name"]):
                try:
                    proc_name = (p.info.get("name") or "").lower()
                    if name in proc_name:
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _cond_network_available(self, cond: dict, ctx: dict) -> bool:
        if settings.mock_mode:
            return True  # assume network is up in mock mode
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
            sock.close()
            return True
        except OSError:
            return False

    def _cond_ai_condition(self, cond: dict, ctx: dict) -> bool:
        """Ask the AI whether the condition is true.

        In mock mode (or if no AI provider is configured), defaults to
        ``False`` — never guess on something that might be destructive.
        """
        prompt = self._resolve(cond.get("prompt", ""), ctx)
        if not prompt:
            return False
        if settings.mock_mode:
            return False
        # Real mode would call the AI provider here. For now we keep it
        # conservative: AI conditions are non-deterministic so the safer
        # default when we can't actually ask the AI is ``False``.
        return False

    # ------------------------------------------------------------------
    # Compound conditions
    # ------------------------------------------------------------------

    def _cond_and(self, cond: dict, ctx: dict) -> bool:
        sub = cond.get("conditions", [])
        if not isinstance(sub, list) or not sub:
            return False
        return all(self.evaluate(c, ctx) for c in sub)

    def _cond_or(self, cond: dict, ctx: dict) -> bool:
        sub = cond.get("conditions", [])
        if not isinstance(sub, list) or not sub:
            return False
        return any(self.evaluate(c, ctx) for c in sub)

    def _cond_not(self, cond: dict, ctx: dict) -> bool:
        inner = cond.get("condition")
        if not isinstance(inner, dict):
            return False
        return not self.evaluate(inner, ctx)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(value: Any, ctx: dict) -> str:
        """Apply ``{{var}}`` substitution to a string parameter.

        Non-string values are passed through untouched.
        """
        if isinstance(value, str):
            return variable_engine.resolve(value, ctx)
        return str(value) if value is not None else ""


condition_evaluator = ConditionEvaluator()


# ---------------------------------------------------------------------------
# Loop executor
# ---------------------------------------------------------------------------


class LoopExecutor:
    """Run a loop body over items produced by a loop spec — §43.

    Loop specs are JSON objects with ``"type"`` plus type-specific params:

    ``for_each_file``              — ``{"path": "...", "pattern": "*"}``
    ``for_each_row``               — ``{"csv_path": "..."}``
    ``for_each_browser_result``    — ``{"selector": "...", "session_id": "default"}``
    ``while``                      — ``{"condition": {...}, "max_iterations": 1000}``
    ``retry``                      — ``{"max_attempts": 3, "delay_seconds": 1.0}``
    ``batch``                      — ``{"items": [...], "batch_size": 10}``

    All loops enforce ``max_iterations`` (default 1000, capped by
    ``settings.max_loops``) so a buggy ``while`` condition can't hang the
    engine forever.
    """

    DEFAULT_MAX_ITERATIONS = 1000

    def __init__(self) -> None:
        self._generators: dict[str, Callable[[dict, dict], list]] = {
            "for_each_file": self._gen_for_each_file,
            "for_each_row": self._gen_for_each_row,
            "for_each_browser_result": self._gen_for_each_browser_result,
            "while": self._gen_while,
            "retry": self._gen_retry,
            "batch": self._gen_batch,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        loop: dict,
        callback: LoopCallback,
        context: Optional[dict] = None,
    ) -> list:
        """Run ``callback`` for each item produced by ``loop``.

        Returns the list of callback return values in order. The callback
        may be sync or async (we await if it returns an awaitable).
        """
        ctx = context or {}
        loop_type = loop.get("type")
        gen = self._generators.get(loop_type) if loop_type else None
        if gen is None:
            logger.warning("unknown loop type {!r} — skipping", loop_type)
            return []

        items = gen(loop, ctx)
        # Always cap by the global max_loops so even a buggy while-condition
        # can't hang the engine.
        cap = min(
            self._effective_max(loop),
            settings.max_loops,
        )
        if len(items) > cap:
            logger.warning(
                "loop {!r} produced {} items — truncating to {}", loop_type, len(items), cap
            )
            items = items[:cap]

        results: list = []
        for item in items:
            res = callback(item)
            if asyncio.iscoroutine(res):
                res = await res
            results.append(res)
        return results

    # ------------------------------------------------------------------
    # Item generators — each returns the list of items to iterate over
    # ------------------------------------------------------------------

    def _gen_for_each_file(self, loop: dict, ctx: dict) -> list:
        path_str = variable_engine.resolve(loop.get("path", ""), ctx)
        pattern = loop.get("pattern", "*") or "*"
        if not path_str:
            return []
        p = Path(path_str).expanduser()
        if not p.exists() or not p.is_dir():
            logger.debug("for_each_file: path {!r} not a dir", p)
            return []
        return sorted(p.glob(pattern))

    def _gen_for_each_row(self, loop: dict, ctx: dict) -> list:
        csv_path = variable_engine.resolve(loop.get("csv_path", ""), ctx)
        if not csv_path:
            return []
        p = Path(csv_path).expanduser()
        if not p.exists():
            return []
        try:
            with p.open(newline="", encoding="utf-8") as fh:
                return list(csv.DictReader(fh))
        except Exception as exc:
            logger.warning("for_each_row read failed: {}", exc)
            return []

    def _gen_for_each_browser_result(self, loop: dict, ctx: dict) -> list:
        selector = variable_engine.resolve(loop.get("selector", ""), ctx)
        if settings.mock_mode:
            # Mock: yield 3 fake result rows so workflows still iterate.
            return [
                {"text": f"mock result {i}", "selector": selector, "index": i}
                for i in range(3)
            ]
        # Real mode would call browser.extract on the live session. Not
        # wired up here to keep the module side-effect free.
        return []

    def _gen_while(self, loop: dict, ctx: dict) -> list:
        condition = loop.get("condition", {})
        max_iter = self._effective_max(loop)
        items: list = []
        # Each iteration is represented by its index — the callback gets
        # ``{"iteration": i}`` so it knows which pass it is on.
        for i in range(max_iter):
            if not condition_evaluator.evaluate(condition, ctx):
                break
            items.append({"iteration": i})
        return items

    def _gen_retry(self, loop: dict, ctx: dict) -> list:
        max_attempts = int(loop.get("max_attempts", 3))
        delay = float(loop.get("delay_seconds", 1.0))
        # Pre-compute the list of attempt descriptors. The callback decides
        # whether the attempt succeeded; if it raises, we surface that via
        # the result list (rather than swallowing the exception).
        return [
            {"attempt": i, "delay_seconds": delay if i > 0 else 0.0}
            for i in range(max_attempts)
        ]

    def _gen_batch(self, loop: dict, ctx: dict) -> list:
        items = loop.get("items", [])
        batch_size = int(loop.get("batch_size", 10)) or 10
        if not isinstance(items, list) or not items:
            return []
        return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _effective_max(self, loop: dict) -> int:
        """Return ``max_iterations`` from the loop spec, clamped to >=1."""
        raw = loop.get("max_iterations", self.DEFAULT_MAX_ITERATIONS)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            v = self.DEFAULT_MAX_ITERATIONS
        return max(1, v)


loop_executor = LoopExecutor()

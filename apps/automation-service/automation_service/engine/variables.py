"""Variables engine — master prompt section 41 (VARIABLES).

Provides ``VariableEngine.resolve(text, context)`` which replaces
``{{var_name}}`` placeholders inside a template string.

Built-in variables are computed lazily so that side-effecting lookups
(clipboard, OS username, timestamp) are only triggered when actually
referenced. Custom variables supplied via ``context`` override built-ins.

Unknown placeholders (e.g. ``{{not_a_real_var}}``) are left as-is so the
caller can detect missing data without raising.

Design notes
------------
* The resolver performs recursive substitution up to ``max_depth`` levels so
  that a variable's value may itself contain ``{{...}}`` patterns. This is
  required by master prompt section 41 ("Allow custom variables") plus the
  example ``filename = "Report_{{today}}.pdf"`` where ``today`` resolves to
  a date but a custom variable could chain through another variable.
* All I/O helpers (``getpass.getuser``, ``pyperclip.paste``) are imported
  lazily so importing this module is side-effect free in headless test
  environments.
"""

from __future__ import annotations

import getpass
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loguru import logger

from ..config import settings


# Pattern matches ``{{var_name}}`` with optional inner whitespace.
# Variable names are restricted to identifier-ish characters: letters,
# digits, underscore, and a dot for nested plugin-style namespaces.
_VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*\}\}")

# Maximum recursion depth when a resolved value itself contains ``{{...}}``.
_MAX_DEPTH = 3


def _safe_clipboard() -> str:
    """Return the current clipboard text or a sentinel if unavailable.

    ``pyperclip`` is optional at runtime (no display server, no clipboard
    daemon, etc.) so we degrade gracefully per master prompt section 64.
    """
    try:
        import pyperclip  # type: ignore

        return pyperclip.paste() or ""
    except Exception as exc:  # pragma: no cover — environment dependent
        logger.debug("clipboard unavailable: {}", exc)
        return "<clipboard_unavailable>"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def _current_time() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _current_datetime() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return str(int(time.time()))


def _username() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover — environment dependent
        return os.getenv("USER") or os.getenv("USERNAME") or "unknown"


def _home_dir() -> str:
    return str(Path.home())


def _downloads_folder() -> str:
    return str(Path.home() / "Downloads")


def _documents_folder() -> str:
    return str(Path.home() / "Documents")


def _desktop_folder() -> str:
    return str(Path.home() / "Desktop")


def _random_uuid() -> str:
    return uuid.uuid4().hex


def _random_int() -> str:
    import random

    return str(random.randint(0, 1000))


# Built-in resolver table — name -> () -> str
#
# Lazy by design: each entry is a zero-arg callable so the value is only
# computed when the variable is actually referenced. This keeps a workflow
# that never uses ``{{clipboard}}`` from touching the system clipboard.
_BUILTIN_RESOLVERS: dict[str, Callable[[], str]] = {
    "today": _today,
    "yesterday": _yesterday,
    "tomorrow": _tomorrow,
    "current_time": _current_time,
    "current_datetime": _current_datetime,
    "timestamp": _timestamp,
    "username": _username,
    "home_dir": _home_dir,
    "downloads_folder": _downloads_folder,
    "documents_folder": _documents_folder,
    "desktop_folder": _desktop_folder,
    "clipboard": _safe_clipboard,
    "random_uuid": _random_uuid,
    "random_int": _random_int,
}


class VariableEngine:
    """Resolves ``{{var}}`` placeholders in strings.

    Usage::

        engine = VariableEngine()
        engine.resolve("Report_{{today}}.pdf", {})
        engine.resolve("Hello {{user}}", {"user": "Alice"})

    Built-ins are always available; values in ``context`` override built-ins.
    Unknown placeholders are left untouched so missing data is visible to the
    caller. Recursive substitution (up to ``max_depth`` levels) allows a
    variable's value to reference another variable.
    """

    def __init__(self, max_depth: int = _MAX_DEPTH) -> None:
        self.max_depth = max_depth

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, text: str, context: Mapping[str, Any]) -> str:
        """Resolve ``{{var}}`` placeholders in ``text``.

        ``context`` is a flat dict mapping variable name -> value. Values may
        be strings, ints, paths, etc. — anything ``str()`` can render.
        Custom context entries override built-in variables of the same name.
        """
        if not isinstance(text, str) or "{{" not in text:
            # Non-template or non-string input — return as-is (well, str()-ified).
            return text if isinstance(text, str) else str(text)

        return self._resolve_recursive(text, dict(context), depth=0)

    def format(self, template: str, **kwargs: Any) -> str:
        """Shortcut for ``resolve(template, kwargs)``."""
        return self.resolve(template, kwargs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_recursive(self, text: str, context: dict[str, Any], depth: int) -> str:
        if depth >= self.max_depth:
            logger.debug("variable resolution hit max_depth={} for: {}", depth, text)
            return text

        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            value = self._lookup(var_name, context)
            if value is None:
                # Unknown — preserve the original placeholder.
                return match.group(0)
            return str(value)

        resolved = _VAR_PATTERN.sub(_replace, text)
        if "{{" in resolved and resolved != text:
            # The substituted value itself may contain ``{{...}}`` — recurse.
            return self._resolve_recursive(resolved, context, depth + 1)
        return resolved

    def _lookup(self, name: str, context: dict[str, Any]) -> Any:
        """Return the value for ``name`` or ``None`` if unknown.

        Order of precedence:
          1. ``context`` dict (caller-supplied) — overrides built-ins.
          2. Built-in lazy resolvers.
          3. ``None`` (unknown — placeholder left untouched).
        """
        if name in context:
            return context[name]
        resolver = _BUILTIN_RESOLVERS.get(name)
        if resolver is None:
            return None
        try:
            return resolver()
        except Exception as exc:
            logger.warning("variable '{}' resolver failed: {}", name, exc)
            return None


# Module-level singleton so callers that just want the default instance
# (e.g. the WorkflowExecutor) can import it without constructing one.
variable_engine = VariableEngine()

"""Concrete trigger implementations for non-APScheduler-native trigger types.

Master prompt section 25 — Triggers.

APScheduler handles SCHEDULE-type triggers natively (cron / interval / date).
This module covers the remaining trigger types from the spec:

* :class:`FileTrigger`       — filesystem watcher (created / modified / moved / deleted)
* :class:`HotkeyTrigger`     — global keyboard shortcut
* :class:`WebhookTrigger`    — exposes a POST endpoint that fires the workflow
* :class:`SystemTrigger`     — startup / login / idle / network-available events

Every trigger exposes the same minimal lifecycle:

    trigger = FileTrigger(file_pattern="*.pdf", events=["created"], callback=fn)
    await trigger.start()
    ...
    await trigger.stop()
    trigger.is_active

The ``callback`` is an ``async`` callable. Each trigger adapts its underlying
library's synchronous notification model onto an ``asyncio`` task so the
event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

# Type alias for the workflow-launch callback every trigger accepts.
TriggerCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# FileTrigger — watchdog-based filesystem watcher
# ---------------------------------------------------------------------------


class FileTrigger:
    """Watches a directory tree for files matching ``file_pattern``.

    Master prompt section 25 — FILE trigger type. Uses ``watchdog`` so the
    kernel-level inotify / FSEvents / ReadDirectoryChangesW backend is used
    instead of polling.

    Parameters
    ----------
    file_pattern:
        Glob pattern (e.g. ``"*.pdf"``) matched against the file path of
        every filesystem event.
    events:
        Whitelist of event types to react to. Supported values: ``created``,
        ``modified``, ``deleted``, ``moved``. Defaults to ``["created"]``.
    watch_dir:
        Directory to watch. Defaults to ``settings.workflows_dir`` if not
        provided. The trigger never recursively watches ``/`` — only the
        given directory (``recursive=True`` is configurable via the kwarg
        of the same name).
    callback:
        Async (or sync) callable invoked with the event payload dict
        ``{"path": str, "event": str, "is_directory": bool}``.
    recursive:
        Whether to descend into subdirectories. Defaults to ``False``.
    """

    SUPPORTED_EVENTS = frozenset({"created", "modified", "deleted", "moved"})

    def __init__(
        self,
        file_pattern: str,
        events: Optional[list[str]] = None,
        watch_dir: Optional[str | Path] = None,
        callback: Optional[TriggerCallback] = None,
        recursive: bool = False,
    ) -> None:
        self.file_pattern = file_pattern
        self.events: set[str] = set(events or ["created"])
        unsupported = self.events - self.SUPPORTED_EVENTS
        if unsupported:
            raise ValueError(
                f"unsupported file events {unsupported!r}; "
                f"valid choices: {sorted(self.SUPPORTED_EVENTS)}"
            )
        self.watch_dir = str(watch_dir) if watch_dir is not None else None
        self.callback = callback
        self.recursive = recursive

        self._observer: Any = None
        self._handler: Optional["_WatchdogHandler"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    async def start(self) -> None:
        """Spawn the watchdog observer.

        Lazy-imports ``watchdog`` so the trigger can be instantiated even on
        systems where watchdog isn't installed (the import only fires here).
        """
        if self._active:
            return
        from watchdog.observers import Observer  # type: ignore[import-not-found]

        # Bind the running loop so the sync handler can schedule callbacks.
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None  # not running inside an event loop

        if self.watch_dir is None:
            from ..config import settings
            self.watch_dir = str(settings.workflows_dir)
        Path(self.watch_dir).mkdir(parents=True, exist_ok=True)

        self._handler = _WatchdogHandler(self)
        self._observer = Observer()
        self._observer.schedule(
            self._handler,
            self.watch_dir,
            recursive=self.recursive,
        )
        self._observer.start()
        self._active = True
        logger.info(
            "FileTrigger started: pattern={!r} dir={!r} events={}",
            self.file_pattern,
            self.watch_dir,
            sorted(self.events),
        )

    async def stop(self) -> None:
        if not self._active:
            return
        try:
            if self._observer is not None:
                self._observer.stop()
                self._observer.join(timeout=2.0)
        finally:
            self._observer = None
            self._handler = None
            self._active = False

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _matches(self, path: str) -> bool:
        return fnmatch.fnmatch(os.path.basename(path), self.file_pattern)

    def _fire(self, event: str, payload: dict[str, Any]) -> None:
        """Schedule the callback on the event loop (non-blocking).

        Watchdog's notifications arrive on its own thread — we cannot call
        ``asyncio.run`` here. Instead, schedule the callback as a task on
        the captured loop.
        """
        if self.callback is None:
            return
        coro = self.callback(payload)
        if asyncio.iscoroutine(coro):
            if self._loop is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self._loop)
            else:
                # No loop running — close the coroutine to silence warnings.
                coro.close()


class _WatchdogHandler:  # pragma: no cover - thin adapter over watchdog.events
    """Translate watchdog FileSystemEvent objects into FileTrigger dispatch."""

    _EVENT_MAP = {
        "created": "on_created",
        "modified": "on_modified",
        "deleted": "on_deleted",
        "moved": "on_moved",
    }

    def __init__(self, owner: FileTrigger) -> None:
        self._owner = owner

    def _dispatch(self, event_name: str, event: Any) -> None:
        if event_name not in self._owner.events:
            return
        src_path = getattr(event, "src_path", "") or ""
        dest_path = getattr(event, "dest_path", "") or ""
        is_dir = bool(getattr(event, "is_directory", False))
        # Match either source or destination (moved events).
        if not (
            self._owner._matches(src_path)
            or (dest_path and self._owner._matches(dest_path))
        ):
            return
        self._owner._fire(
            event_name,
            {
                "path": src_path,
                "dest_path": dest_path,
                "event": event_name,
                "is_directory": is_dir,
            },
        )

    # watchdog calls these via the FileSystemEventHandler protocol
    def on_created(self, event: Any) -> None:
        self._dispatch("created", event)

    def on_modified(self, event: Any) -> None:
        self._dispatch("modified", event)

    def on_deleted(self, event: Any) -> None:
        self._dispatch("deleted", event)

    def on_moved(self, event: Any) -> None:
        self._dispatch("moved", event)


# ---------------------------------------------------------------------------
# HotkeyTrigger — pynput-based global shortcut listener
# ---------------------------------------------------------------------------


class HotkeyTrigger:
    """Listens for a global keyboard shortcut.

    Master prompt section 25 — HOTKEY trigger type. Uses ``pynput``'s
    :class:`GlobalHotKeys` listener. The shortcut format is the same one
    pynput expects: ``"<ctrl>+<shift>+a"`` — modifiers wrapped in angle
    brackets, joined by ``+``.

    Because pynput requires a running display server (X11 / Windows
    desktop), the import is performed lazily inside :meth:`start`. On
    headless systems the start call raises a clear error so the caller can
    degrade gracefully (e.g. skip the trigger in mock mode).
    """

    def __init__(
        self,
        hotkey: str,
        callback: Optional[TriggerCallback] = None,
    ) -> None:
        self.hotkey = self._normalize(hotkey)
        self.callback = callback
        self._listener: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active: bool = False

    # ------------------------------------------------------------------
    # Normalization — accept "ctrl+shift+a" or "<ctrl>+<shift>+a"
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(hotkey: str) -> str:
        """Accept both ``ctrl+shift+a`` and ``<ctrl>+<shift>+a``.

        pynput's GlobalHotKeys expects the latter (with angle brackets).
        Single character keys are left bare. This makes the public API
        match the rest of the project (where modifiers are written
        without angle brackets, e.g. ``settings.emergency_stop_shortcut``).
        """
        modifiers = {"ctrl", "alt", "shift", "cmd", "win", "altgr"}
        parts = [p.strip() for p in hotkey.split("+") if p.strip()]
        out: list[str] = []
        for p in parts:
            if p.lower() in modifiers and not (p.startswith("<") and p.endswith(">")):
                out.append(f"<{p.lower()}>")
            elif p.lower() in modifiers and p.startswith("<"):
                out.append(p.lower())
            else:
                # bare key (letter, digit, function key)
                out.append(p.lower())
        return "+".join(out)

    @property
    def is_active(self) -> bool:
        return self._active

    async def start(self) -> None:
        if self._active:
            return
        try:
            from pynput import keyboard  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - platform-dependent
            raise RuntimeError(
                "HotkeyTrigger requires pynput with a running display server"
            ) from exc

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        trigger = self

        def _on_activate() -> None:
            payload = {"hotkey": trigger.hotkey, "at": time.time()}
            if trigger.callback is None:
                return
            coro = trigger.callback(payload)
            if asyncio.iscoroutine(coro):
                if trigger._loop is not None and trigger._loop.is_running():
                    asyncio.run_coroutine_threadsafe(coro, trigger._loop)
                else:
                    coro.close()

        # GlobalHotKeys takes a dict mapping shortcut-string -> callable
        self._listener = keyboard.GlobalHotKeys(
            {self.hotkey: _on_activate}
        )
        self._listener.start()
        self._active = True
        logger.info("HotkeyTrigger started: {}", self.hotkey)

    async def stop(self) -> None:
        if not self._active:
            return
        try:
            if self._listener is not None:
                self._listener.stop()
        finally:
            self._listener = None
            self._active = False


# ---------------------------------------------------------------------------
# WebhookTrigger — exposes a POST endpoint that fires the workflow
# ---------------------------------------------------------------------------


class WebhookTrigger:
    """Registers a POST endpoint under ``/webhooks/{token}``.

    Master prompt section 25 — WEBHOOK trigger type. The trigger does NOT
    spin up its own HTTP server; instead it stashes its callback in a
    module-level registry that the FastAPI app consults. When a POST
    request arrives at ``{webhook_url}``, the registry routes the payload
    to the trigger's callback.

    The token in the URL acts as an unguessable secret — the caller
    generates one when scheduling the webhook trigger.
    """

    # Module-level registry: {url_path: WebhookTrigger}
    _REGISTRY: dict[str, "WebhookTrigger"] = {}
    _REGISTRY_LOCK = threading.Lock()

    def __init__(
        self,
        webhook_url: str,
        callback: Optional[TriggerCallback] = None,
    ) -> None:
        # Normalize: always start with a leading slash, no trailing slash.
        if not webhook_url.startswith("/"):
            webhook_url = "/" + webhook_url
        self.webhook_url = webhook_url.rstrip("/") or "/"
        self.callback = callback
        self._active: bool = False

    @property
    def is_active(self) -> bool:
        return self._active

    @classmethod
    def get_trigger_for_url(cls, url: str) -> Optional["WebhookTrigger"]:
        """Look up the active trigger registered for the given URL path."""
        path = url if url.startswith("/") else "/" + url
        path = path.rstrip("/") or "/"
        with cls._REGISTRY_LOCK:
            return cls._REGISTRY.get(path)

    async def start(self) -> None:
        if self._active:
            return
        with self._REGISTRY_LOCK:
            self._REGISTRY[self.webhook_url] = self
        self._active = True
        logger.info("WebhookTrigger registered at {}", self.webhook_url)

    async def stop(self) -> None:
        if not self._active:
            return
        with self._REGISTRY_LOCK:
            self._REGISTRY.pop(self.webhook_url, None)
        self._active = False

    async def fire(self, payload: dict[str, Any]) -> None:
        """Called by the FastAPI webhook route when a POST arrives."""
        if self.callback is None:
            return
        coro = self.callback(payload)
        if asyncio.iscoroutine(coro):
            await coro


# ---------------------------------------------------------------------------
# SystemTrigger — startup / login / idle / network-available
# ---------------------------------------------------------------------------


class SystemTrigger:
    """Listens for OS-level events: startup, login, idle, network.

    Master prompt section 25 — SYSTEM trigger type.

    * ``startup``         — fires once when the trigger is started (the
      service itself starting is treated as the system event).
    * ``login``           — fires when psutil reports a new interactive
      user session.
    * ``idle``            — polls psutil; fires after ``idle_seconds`` of
      no new input (the master prompt specifies "no input for N seconds").
    * ``network_available`` — polls the OS network interfaces; fires once
      when at least one non-loopback interface has an IP.

    All polling is done on a background asyncio task so the event loop is
    never blocked.
    """

    SUPPORTED_EVENTS = frozenset(
        {"startup", "login", "idle", "network_available"}
    )
    _POLL_INTERVAL_SECONDS = 5.0

    def __init__(
        self,
        event: str,
        callback: Optional[TriggerCallback] = None,
        idle_seconds: int = 300,
    ) -> None:
        if event not in self.SUPPORTED_EVENTS:
            raise ValueError(
                f"unsupported system event {event!r}; "
                f"valid choices: {sorted(self.SUPPORTED_EVENTS)}"
            )
        self.event = event
        self.callback = callback
        self.idle_seconds = idle_seconds
        self._task: Optional[asyncio.Task[None]] = None
        self._active: bool = False
        self._last_input_ts: float = time.time()
        self._last_login_count: int = 0
        self._network_seen: bool = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def start(self) -> None:
        if self._active:
            return
        self._active = True
        # Initialize counters so we don't immediately fire on the first poll
        # for login / network_available (those are state-change events).
        self._last_input_ts = time.time()
        try:
            self._last_login_count = self._count_login_sessions()
        except Exception:
            self._last_login_count = 0
        self._network_seen = self._has_network()

        # startup fires immediately
        if self.event == "startup":
            await self._fire({"event": "startup", "at": time.time()})
        else:
            # Begin polling loop for login / idle / network_available
            self._task = asyncio.create_task(self._poll_loop())
        logger.info("SystemTrigger started: event={}", self.event)

    async def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # ------------------------------------------------------------------
    # Polling helpers
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._active:
            try:
                if self.event == "login":
                    await self._check_login()
                elif self.event == "idle":
                    await self._check_idle()
                elif self.event == "network_available":
                    await self._check_network()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("SystemTrigger poll error: {}", exc)
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)

    async def _check_login(self) -> None:
        current = self._count_login_sessions()
        if current > self._last_login_count:
            await self._fire(
                {"event": "login", "sessions": current, "at": time.time()}
            )
        self._last_login_count = current

    async def _check_idle(self) -> None:
        now = time.time()
        # No reliable cross-platform idle API without extra deps — we use
        # psutil.users() (treats "no users" as idle). For real desktop idle
        # detection the deployer would replace this with xprintidle / Win32
        # GetLastInputInfo. The hook is mockable in tests by patching
        # SystemTrigger._count_login_sessions.
        users = self._count_login_sessions()
        if users == 0 and (now - self._last_input_ts) >= self.idle_seconds:
            await self._fire(
                {"event": "idle", "idle_seconds": now - self._last_input_ts, "at": now}
            )
        elif users > 0:
            self._last_input_ts = now

    async def _check_network(self) -> None:
        has_net = self._has_network()
        if has_net and not self._network_seen:
            await self._fire({"event": "network_available", "at": time.time()})
        self._network_seen = has_net

    async def _fire(self, payload: dict[str, Any]) -> None:
        if self.callback is None:
            return
        coro = self.callback(payload)
        if asyncio.iscoroutine(coro):
            await coro

    # ------------------------------------------------------------------
    # Mockable probes
    # ------------------------------------------------------------------

    @staticmethod
    def _count_login_sessions() -> int:
        """Return the number of interactive user sessions.

        Uses ``psutil.users()`` which returns a list of ``suser`` named
        tuples. The default ``len(psutil.users())`` is the right metric on
        Linux / macOS / Windows.
        """
        try:
            import psutil  # type: ignore[import-not-found]
            return len(psutil.users())
        except Exception:
            return 0

    @staticmethod
    def _has_network() -> bool:
        """Return True if at least one non-loopback interface has an IP."""
        try:
            import psutil  # type: ignore[import-not-found]
            stats = psutil.net_if_addrs()
            for name, addrs in stats.items():
                if name.lower() in {"lo", "loopback"}:
                    continue
                for addr in addrs:
                    # AF_INET = IPv4, AF_INET6 = IPv6 — both count.
                    family = getattr(addr, "family", None)
                    ip = getattr(addr, "address", "") or ""
                    if family in (2, 10) and ip and not ip.startswith("127."):
                        return True
            return False
        except Exception:
            return False

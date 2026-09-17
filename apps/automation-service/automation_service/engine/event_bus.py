"""In-process async event bus — master prompt §76.

Events are produced by the workflow executor, tool executions, and the kill
switch. The FastAPI WebSocket endpoint subscribes to push events to the
Electron renderer live.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable


# Canonical event names from master prompt §76
EVENT_TYPES = [
    "TASK_CREATED",
    "TASK_STARTED",
    "TASK_PAUSED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "STEP_STARTED",
    "STEP_COMPLETED",
    "STEP_FAILED",
    "APP_OPENED",
    "APP_CLOSED",
    "WINDOW_CHANGED",
    "BROWSER_NAVIGATED",
    "FILE_CREATED",
    "FILE_MOVED",
    "USER_APPROVAL_REQUIRED",
    "EMERGENCY_STOP",
    "SERVICE_STARTED",
    "SERVICE_STOPPED",
    "UNHANDLED_ERROR",
]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[tuple[str, dict[str, Any]]]] = []
        self._sync_handlers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        self._async_handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = defaultdict(list)

    def subscribe(self) -> asyncio.Queue[tuple[str, dict[str, Any]]]:
        """Returns an async queue that receives every published event."""
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def on(self, event_type: str, handler: Callable[[dict], None]) -> None:
        self._sync_handlers[event_type].append(handler)

    def on_async(self, event_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._async_handlers[event_type].append(handler)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        # Run sync handlers immediately
        for handler in self._sync_handlers.get(event_type, []):
            try:
                handler(payload)
            except Exception as exc:
                # Don't let a buggy handler kill the bus
                print(f"[event_bus] sync handler error for {event_type}: {exc}")

        # Schedule async handlers
        for handler in self._async_handlers.get(event_type, []):
            try:
                asyncio.create_task(handler(payload))
            except Exception as exc:
                print(f"[event_bus] async handler error for {event_type}: {exc}")

        # Push to subscriber queues
        for q in self._subscribers:
            try:
                q.put_nowait((event_type, payload))
            except asyncio.QueueFull:
                # Drop oldest to make room
                try:
                    q.get_nowait()
                    q.put_nowait((event_type, payload))
                except Exception:
                    pass


event_bus = EventBus()

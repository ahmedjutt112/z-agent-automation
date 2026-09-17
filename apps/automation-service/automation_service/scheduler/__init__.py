"""Scheduler subsystem — master prompt section 24 (Scheduler) + section 25 (Triggers).

Public surface:

* :class:`SchedulerManager` — singleton wrapping APScheduler's
  :class:`AsyncIOScheduler`. Translate our :class:`TriggerType` enum into
  APScheduler trigger classes, persist job state to the
  ``scheduled_jobs`` SQLAlchemy table, and emit lifecycle events via the
  in-process :data:`event_bus`.
* :class:`FileTrigger`, :class:`HotkeyTrigger`, :class:`WebhookTrigger`,
  :class:`SystemTrigger` — concrete trigger implementations for the
  trigger types that aren't native to APScheduler.
* :data:`scheduler_manager` — module-level singleton instance. Import this
  from ``automation_service.main`` (lifespan) and from the FastAPI router.
* :data:`schedules_router` — FastAPI APIRouter mounted under ``/schedules``.
"""

from __future__ import annotations

from .manager import SchedulerManager, scheduler_manager
from .triggers import (
    FileTrigger,
    HotkeyTrigger,
    SystemTrigger,
    WebhookTrigger,
)
from .api import router as schedules_router

__all__ = [
    "SchedulerManager",
    "scheduler_manager",
    "FileTrigger",
    "HotkeyTrigger",
    "WebhookTrigger",
    "SystemTrigger",
    "schedules_router",
]

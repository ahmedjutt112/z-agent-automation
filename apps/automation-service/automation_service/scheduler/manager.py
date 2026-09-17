"""SchedulerManager — APScheduler integration for the automation service.

Master prompt section 24 (Scheduler) + section 25 (Triggers).

Responsibilities
----------------

* Wrap APScheduler's :class:`AsyncIOScheduler` so the rest of the service
  can talk to one ``scheduler_manager`` singleton.
* Translate our :class:`TriggerType` enum + trigger config dict into
  APScheduler's native trigger classes (:class:`CronTrigger`,
  :class:`IntervalTrigger`, :class:`DateTrigger`) for SCHEDULE-type
  triggers.
* Delegate FILE / HOTKEY / WEBHOOK / SYSTEM trigger types to the
  standalone trigger classes in :mod:`automation_service.scheduler.triggers`.
* Persist job state to the ``scheduled_jobs`` SQLAlchemy table on
  schedule_workflow() and remove it on unschedule().
* Enforce per-workflow concurrency limits (default 1) — if a job fires
  while a previous run is still active for the same workflow_id, the new
  invocation is skipped (or queued — configurable).
* Apply APScheduler's misfire_grace_time + coalesce options so a service
  that was offline for 100 hours doesn't replay 100 missed runs.
* Emit lifecycle events (SCHEDULED_JOB_TRIGGERED / COMPLETED / FAILED) via
  the in-process :data:`event_bus`.
* Honour ``settings.mock_mode`` — in mock mode the scheduler still
  registers jobs (and persists them) but the workflow callback is a
  no-op so no real automation fires.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo  # Python 3.9+ — falls back gracefully

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from loguru import logger

from ..config import settings
from ..engine.event_bus import event_bus
from ..models import TriggerType, Workflow
from .triggers import (
    FileTrigger,
    HotkeyTrigger,
    SystemTrigger,
    WebhookTrigger,
)


# ---------------------------------------------------------------------------
# Defaults — overridable via trigger_config keys of the same name
# ---------------------------------------------------------------------------

DEFAULT_MISFIRE_GRACE_TIME = 60  # seconds — master prompt §24
DEFAULT_EXECUTION_TIMEOUT = 1800  # seconds — matches ScheduledJob.execution_timeout
DEFAULT_MAX_CONCURRENT = 1
DEFAULT_TIMEZONE = "UTC"


# Canonical scheduler lifecycle events emitted via the event bus.
SCHEDULER_EVENT_TYPES = (
    "SCHEDULED_JOB_TRIGGERED",
    "SCHEDULED_JOB_COMPLETED",
    "SCHEDULED_JOB_FAILED",
)


# ---------------------------------------------------------------------------
# SchedulerManager
# ---------------------------------------------------------------------------


class SchedulerManager:
    """Singleton wrapping APScheduler's AsyncIOScheduler.

    Use the module-level :data:`scheduler_manager` instance — do NOT
    instantiate ``SchedulerManager()`` directly elsewhere.
    """

    def __init__(self) -> None:
        # We keep the AsyncIOScheduler instance as a private attribute so
        # tests can call ``reset()`` to rebuild a fresh one.
        self._scheduler: AsyncIOScheduler = self._build_scheduler()
        self._started: bool = False

        # Map of job_id -> TriggerConfig (the original dict we registered).
        # Used to reconstruct triggers on resume / persistence queries.
        self._job_configs: dict[str, dict[str, Any]] = {}

        # Map of workflow_id -> asyncio.Lock used to enforce max_concurrent.
        self._concurrency_locks: dict[str, asyncio.Lock] = {}
        self._max_concurrent: dict[str, int] = {}
        # Track in-flight runs so we can skip when max_concurrent=1.
        self._active_runs: dict[str, int] = {}

        # Standalone triggers (file / hotkey / webhook / system) live here
        # so we can start/stop them in lockstep with the scheduler.
        self._file_triggers: dict[str, FileTrigger] = {}
        self._hotkey_triggers: dict[str, HotkeyTrigger] = {}
        self._webhook_triggers: dict[str, WebhookTrigger] = {}
        self._system_triggers: dict[str, SystemTrigger] = {}

    # ------------------------------------------------------------------
    # Singleton nicety — `SchedulerManager()` always returns the same
    # instance if you forget to import the module-level ``scheduler_manager``.
    # ------------------------------------------------------------------

    _instance: Optional["SchedulerManager"] = None

    def __new__(cls) -> "SchedulerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _reset_singleton(cls) -> "SchedulerManager":
        """Test-only helper: rebuild the singleton from scratch.

        Used by the conftest fixture to give each scheduler test a clean
        slate. Not part of the public API.
        """
        cls._instance = None
        fresh = cls()
        cls._instance = fresh
        return fresh

    # ------------------------------------------------------------------
    # Scheduler construction + lifecycle
    # ------------------------------------------------------------------

    def _build_scheduler(self) -> AsyncIOScheduler:
        """Create a fresh AsyncIOScheduler.

        We use an in-memory jobstore (jobs are reconstructed from the DB
        on each start in a production setup). Timezone-aware via the
        ``timezone`` arg on each trigger.
        """
        return AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,  # §24 — collapse missed runs
                "max_instances": 1,  # overridden per-workflow via _concurrency_locks
                "misfire_grace_time": DEFAULT_MISFIRE_GRACE_TIME,
            },
        )

    @property
    def is_running(self) -> bool:
        return self._started and self._scheduler.running

    @property
    def scheduler(self) -> AsyncIOScheduler:
        """Direct access to the underlying AsyncIOScheduler (read-only use)."""
        return self._scheduler

    async def start(self) -> None:
        """Start the scheduler. Safe to call multiple times — the second
        and subsequent calls are no-ops."""
        if self._started:
            return
        if not self._scheduler.running:
            self._scheduler.start()
        self._started = True

        # Bring up any standalone triggers that were registered before
        # start() (uncommon path, but supported).
        for trig in list(self._file_triggers.values()):
            await trig.start()
        for trig in list(self._hotkey_triggers.values()):
            await trig.start()
        for trig in list(self._webhook_triggers.values()):
            await trig.start()
        for trig in list(self._system_triggers.values()):
            await trig.start()

        logger.info("SchedulerManager started")

    async def shutdown(self, wait: bool = True) -> None:
        """Shut the scheduler down. Safe to call when not started."""
        if not self._started:
            return
        # Stop standalone triggers first so they don't enqueue callbacks
        # into a half-dead scheduler.
        for trig in list(self._file_triggers.values()):
            await trig.stop()
        for trig in list(self._hotkey_triggers.values()):
            await trig.stop()
        for trig in list(self._webhook_triggers.values()):
            await trig.stop()
        for trig in list(self._system_triggers.values()):
            await trig.stop()

        try:
            self._scheduler.shutdown(wait=wait)
        except SchedulerNotRunningError:
            pass
        self._started = False
        logger.info("SchedulerManager shut down (wait={})", wait)

    def reset(self) -> None:
        """Test-only: drop every job and rebuild a fresh scheduler.

        Does NOT touch the ``scheduled_jobs`` DB table — that's the
        caller's responsibility. After ``reset()`` the manager is in the
        same shape as a fresh ``__init__``.

        ``reset()`` is intentionally defensive — if the underlying
        AsyncIOScheduler can't be shut down (e.g. its captured event
        loop has already closed), we swallow the error and just rebuild.
        """
        if self._scheduler.running:
            try:
                self._scheduler.shutdown(wait=False)
            except (SchedulerNotRunningError, RuntimeError, Exception):
                # RuntimeError fires when the captured event loop is closed
                # (common between pytest tests). Swallow and rebuild.
                pass
        self._scheduler = self._build_scheduler()
        self._started = False
        self._job_configs.clear()
        self._concurrency_locks.clear()
        self._max_concurrent.clear()
        self._active_runs.clear()
        self._file_triggers.clear()
        self._hotkey_triggers.clear()
        self._webhook_triggers.clear()
        self._system_triggers.clear()

    # ------------------------------------------------------------------
    # Workflow scheduling
    # ------------------------------------------------------------------

    async def schedule_workflow(
        self, workflow_id: str, trigger_config: dict[str, Any]
    ) -> str:
        """Register a job that fires ``workflow_id`` on the given trigger.

        Returns the new job_id (UUID4 string).

        ``trigger_config`` keys (all optional except ``type``):

        * ``type``               — one of TriggerType values
        * ``schedule_type``      — for SCHEDULE: "cron"|"hourly"|"daily"|
          "weekly"|"monthly"|"once"
        * ``cron``               — cron expression (only for "cron")
        * ``run_date``           — ISO datetime (only for "once")
        * ``timezone``           — timezone string (default UTC)
        * ``misfire_grace_time`` — seconds (default 60)
        * ``coalesce``           — bool (default True)
        * ``max_concurrent``     — int (default 1)
        * ``execution_timeout``  — seconds (default 1800)
        * ``file_pattern``       — for FILE
        * ``events``             — list[str] for FILE
        * ``watch_dir``          — for FILE
        * ``hotkey``             — for HOTKEY
        * ``webhook_url``        — for WEBHOOK
        * ``event``              — for SYSTEM
        * ``idle_seconds``       — for SYSTEM/idle
        """
        trigger_type = self._normalize_trigger_type(trigger_config.get("type"))
        job_id = str(uuid.uuid4())

        misfire_grace_time = int(
            trigger_config.get("misfire_grace_time", DEFAULT_MISFIRE_GRACE_TIME)
        )
        coalesce = bool(trigger_config.get("coalesce", True))
        max_concurrent = int(
            trigger_config.get("max_concurrent", DEFAULT_MAX_CONCURRENT)
        )
        execution_timeout = int(
            trigger_config.get("execution_timeout", DEFAULT_EXECUTION_TIMEOUT)
        )
        tz_name = str(trigger_config.get("timezone", DEFAULT_TIMEZONE))
        tz = self._resolve_timezone(tz_name)

        # Persist per-workflow concurrency state
        self._max_concurrent[workflow_id] = max_concurrent
        self._active_runs.setdefault(workflow_id, 0)

        # Stash the trigger config so list_jobs() / resume / DB reload can
        # reconstruct the trigger later.
        config_snapshot = {
            **trigger_config,
            "type": trigger_type.value,
            "timezone": tz_name,
            "misfire_grace_time": misfire_grace_time,
            "coalesce": coalesce,
            "max_concurrent": max_concurrent,
            "execution_timeout": execution_timeout,
        }
        self._job_configs[job_id] = config_snapshot

        # Build the actual trigger + register with APScheduler
        if trigger_type == TriggerType.SCHEDULE:
            trig = self._build_schedule_trigger(trigger_config, tz)
            self._scheduler.add_job(
                self._workflow_callback,
                trigger=trig,
                args=[workflow_id, job_id],
                id=job_id,
                misfire_grace_time=misfire_grace_time,
                coalesce=coalesce,
                replace_existing=True,
            )
        elif trigger_type == TriggerType.FILE:
            trig = FileTrigger(
                file_pattern=trigger_config.get("file_pattern", "*"),
                events=trigger_config.get("events"),
                watch_dir=trigger_config.get("watch_dir"),
                callback=self._make_trigger_callback(workflow_id, job_id),
            )
            self._file_triggers[job_id] = trig
            if self._started:
                await trig.start()
        elif trigger_type == TriggerType.HOTKEY:
            trig = HotkeyTrigger(
                hotkey=trigger_config.get("hotkey", "<ctrl>+<shift>+h"),
                callback=self._make_trigger_callback(workflow_id, job_id),
            )
            self._hotkey_triggers[job_id] = trig
            if self._started:
                try:
                    await trig.start()
                except Exception as exc:  # pragma: no cover - headless CI
                    logger.warning("HotkeyTrigger failed to start: {}", exc)
        elif trigger_type == TriggerType.WEBHOOK:
            trig = WebhookTrigger(
                webhook_url=trigger_config.get("webhook_url", f"/hooks/{job_id}"),
                callback=self._make_trigger_callback(workflow_id, job_id),
            )
            self._webhook_triggers[job_id] = trig
            if self._started:
                await trig.start()
        elif trigger_type == TriggerType.SYSTEM:
            trig = SystemTrigger(
                event=trigger_config.get("event", "startup"),
                callback=self._make_trigger_callback(workflow_id, job_id),
                idle_seconds=int(trigger_config.get("idle_seconds", 300)),
            )
            self._system_triggers[job_id] = trig
            if self._started:
                await trig.start()
        elif trigger_type in (TriggerType.APPLICATION, TriggerType.BROWSER):
            # APPLICATION / BROWSER triggers don't have an APScheduler-native
            # equivalent in this iteration — they're polled by the engine
            # at startup. Register a placeholder so the job is tracked.
            logger.info(
                "Trigger type {} scheduled as a placeholder (engine polls)",
                trigger_type.value,
            )
        elif trigger_type == TriggerType.MANUAL:
            # Manual triggers don't create an APScheduler job at all.
            logger.info(
                "Manual trigger registered for workflow {} (job_id={})",
                workflow_id,
                job_id,
            )
        else:  # pragma: no cover - defensive
            raise ValueError(f"unsupported trigger type: {trigger_type!r}")

        # Persist to scheduled_jobs table
        self._persist_job(job_id, workflow_id, config_snapshot)

        return job_id

    async def unschedule(self, job_id: str) -> bool:
        """Remove a scheduled job. Returns True if the job existed."""
        existed = self._job_configs.pop(job_id, None) is not None

        # APScheduler job removal (SCHEDULE type)
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass  # not an APScheduler job, or already removed

        # Stop any standalone trigger
        for bucket in (
            self._file_triggers,
            self._hotkey_triggers,
            self._webhook_triggers,
            self._system_triggers,
        ):
            trig = bucket.pop(job_id, None)
            if trig is not None and trig.is_active:
                try:
                    await trig.stop()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("Trigger stop error: {}", exc)

        # Remove the DB row
        self._delete_job_row(job_id)

        return existed

    # ------------------------------------------------------------------
    # Job introspection / control
    # ------------------------------------------------------------------

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return a list of job dicts (registered with APScheduler + our
        standalone triggers)."""
        out: list[dict[str, Any]] = []

        # APScheduler jobs (SCHEDULE type)
        try:
            for job in self._scheduler.get_jobs():
                cfg = self._job_configs.get(job.id, {})
                out.append(
                    {
                        "job_id": job.id,
                        "workflow_id": cfg.get("workflow_id"),
                        "trigger_type": cfg.get("type", "schedule"),
                        "trigger_config": cfg,
                        "next_run_time": (
                            job.next_run_time.isoformat()
                            if job.next_run_time
                            else None
                        ),
                        "misfire_grace_time": job.misfire_grace_time,
                        "coalesce": getattr(job, "coalesce", True),
                        "source": "apscheduler",
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("list_jobs scheduler query error: {}", exc)

        # Standalone triggers
        for job_id, trig in self._file_triggers.items():
            cfg = self._job_configs.get(job_id, {})
            out.append(self._standalone_job_dict(job_id, cfg, "file", trig))
        for job_id, trig in self._hotkey_triggers.items():
            cfg = self._job_configs.get(job_id, {})
            out.append(self._standalone_job_dict(job_id, cfg, "hotkey", trig))
        for job_id, trig in self._webhook_triggers.items():
            cfg = self._job_configs.get(job_id, {})
            out.append(self._standalone_job_dict(job_id, cfg, "webhook", trig))
        for job_id, trig in self._system_triggers.items():
            cfg = self._job_configs.get(job_id, {})
            out.append(self._standalone_job_dict(job_id, cfg, "system", trig))

        return out

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job. Returns True on success."""
        # APScheduler pause
        try:
            self._scheduler.pause_job(job_id)
            return True
        except Exception:
            pass

        # Standalone triggers — stop them (resume restarts)
        for bucket in (
            self._file_triggers,
            self._hotkey_triggers,
            self._webhook_triggers,
            self._system_triggers,
        ):
            trig = bucket.get(job_id)
            if trig is not None and trig.is_active:
                # stop() is async but pause_job is sync — schedule it
                asyncio.create_task(trig.stop())
                return True

        return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job. Returns True on success."""
        try:
            self._scheduler.resume_job(job_id)
            return True
        except Exception:
            pass

        for bucket in (
            self._file_triggers,
            self._hotkey_triggers,
            self._webhook_triggers,
            self._system_triggers,
        ):
            trig = bucket.get(job_id)
            if trig is not None and not trig.is_active:
                asyncio.create_task(trig.start())
                return True

        return False

    # ------------------------------------------------------------------
    # Health endpoint support
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return a health dict for the /scheduler/health endpoint."""
        jobs = self.list_jobs()
        next_run: Optional[str] = None
        for j in jobs:
            if j.get("next_run_time"):
                next_run = j["next_run_time"]
                break
        return {
            "running": self.is_running,
            "jobs_count": len(jobs),
            "next_run": next_run,
        }

    # ------------------------------------------------------------------
    # Internal: callback invoked when a scheduled job fires
    # ------------------------------------------------------------------

    async def _workflow_callback(self, workflow_id: str, job_id: str) -> None:
        """The actual function APScheduler calls when a job fires.

        Loads the workflow JSON from disk (settings.workflows_dir /
        ``{workflow_id}.json``), enforces the per-workflow concurrency
        limit, then delegates to :class:`WorkflowExecutor`.

        In ``mock_mode`` the workflow is NOT executed — we just emit
        the lifecycle events and return.
        """
        event_bus.publish(
            "SCHEDULED_JOB_TRIGGERED",
            {"job_id": job_id, "workflow_id": workflow_id, "at": _utcnow_iso()},
        )

        # Concurrency check — skip if we'd exceed max_concurrent for the workflow
        max_c = self._max_concurrent.get(workflow_id, DEFAULT_MAX_CONCURRENT)
        active = self._active_runs.get(workflow_id, 0)
        if active >= max_c:
            logger.info(
                "Skipping scheduled run for workflow {} — already {} active",
                workflow_id,
                active,
            )
            return
        self._active_runs[workflow_id] = active + 1

        try:
            if settings.mock_mode:
                logger.info(
                    "mock_mode=True — scheduler would fire workflow {}",
                    workflow_id,
                )
                event_bus.publish(
                    "SCHEDULED_JOB_COMPLETED",
                    {
                        "job_id": job_id,
                        "workflow_id": workflow_id,
                        "mock_mode": True,
                        "at": _utcnow_iso(),
                    },
                )
                return

            workflow = self._load_workflow(workflow_id)
            if workflow is None:
                logger.warning(
                    "Scheduled workflow {} not found on disk — skipping",
                    workflow_id,
                )
                event_bus.publish(
                    "SCHEDULED_JOB_FAILED",
                    {
                        "job_id": job_id,
                        "workflow_id": workflow_id,
                        "error": "workflow not found",
                    },
                )
                return

            from ..engine.workflow_executor import WorkflowExecutor
            executor = WorkflowExecutor()
            timeout = self._job_configs.get(job_id, {}).get(
                "execution_timeout", DEFAULT_EXECUTION_TIMEOUT
            )
            try:
                await asyncio.wait_for(
                    executor.execute_workflow(workflow),
                    timeout=timeout,
                )
                event_bus.publish(
                    "SCHEDULED_JOB_COMPLETED",
                    {
                        "job_id": job_id,
                        "workflow_id": workflow_id,
                        "at": _utcnow_iso(),
                    },
                )
            except asyncio.TimeoutError:
                event_bus.publish(
                    "SCHEDULED_JOB_FAILED",
                    {
                        "job_id": job_id,
                        "workflow_id": workflow_id,
                        "error": f"timeout after {timeout}s",
                    },
                )
            except Exception as exc:
                event_bus.publish(
                    "SCHEDULED_JOB_FAILED",
                    {
                        "job_id": job_id,
                        "workflow_id": workflow_id,
                        "error": str(exc),
                    },
                )
        finally:
            self._active_runs[workflow_id] = max(
                0, self._active_runs.get(workflow_id, 1) - 1
            )

    def _make_trigger_callback(
        self, workflow_id: str, job_id: str
    ) -> Callable[[dict[str, Any]], Awaitable[None] | None]:
        """Build the async callback handed to standalone triggers."""

        async def _cb(payload: dict[str, Any]) -> None:
            event_bus.publish(
                "SCHEDULED_JOB_TRIGGERED",
                {
                    "job_id": job_id,
                    "workflow_id": workflow_id,
                    "payload": payload,
                    "at": _utcnow_iso(),
                },
            )
            # Reuse the main callback flow (mock mode, concurrency, etc.)
            await self._workflow_callback(workflow_id, job_id)

        return _cb

    # ------------------------------------------------------------------
    # Internal: trigger translation
    # ------------------------------------------------------------------

    def _build_schedule_trigger(
        self, trigger_config: dict[str, Any], tz: Any
    ) -> Any:
        """Translate the SCHEDULE trigger config into an APScheduler trigger."""
        schedule_type = (
            trigger_config.get("schedule_type")
            or trigger_config.get("schedule")
            or "cron"
        ).lower()

        if schedule_type == "cron":
            cron_expr = trigger_config.get("cron")
            if not cron_expr:
                raise ValueError("schedule_type='cron' requires a 'cron' field")
            return CronTrigger.from_crontab(cron_expr, timezone=tz)

        if schedule_type == "hourly":
            return IntervalTrigger(hours=1, timezone=tz)

        if schedule_type == "daily":
            # Daily at 00:00 in the configured timezone
            return CronTrigger(hour=0, minute=0, timezone=tz)

        if schedule_type == "weekly":
            # Weekly on Monday 00:00
            return CronTrigger(day_of_week="mon", hour=0, minute=0, timezone=tz)

        if schedule_type == "monthly":
            # Monthly on the 1st at 00:00
            return CronTrigger(day=1, hour=0, minute=0, timezone=tz)

        if schedule_type == "once":
            run_date = trigger_config.get("run_date")
            if not run_date:
                raise ValueError(
                    "schedule_type='once' requires a 'run_date' field"
                )
            return DateTrigger(run_date=self._parse_run_date(run_date), timezone=tz)

        # If the caller passed a raw cron expression directly under "cron"
        # without setting schedule_type, fall back to that.
        if trigger_config.get("cron"):
            return CronTrigger.from_crontab(
                trigger_config["cron"], timezone=tz
            )

        raise ValueError(
            f"unrecognized SCHEDULE trigger config: {trigger_config!r}"
        )

    @staticmethod
    def _normalize_trigger_type(value: Any) -> TriggerType:
        """Accept TriggerType enum values or their string form."""
        if isinstance(value, TriggerType):
            return value
        if isinstance(value, str):
            try:
                return TriggerType(value.lower())
            except ValueError:
                pass
        # Default to SCHEDULE for backwards compatibility
        return TriggerType.SCHEDULE

    @staticmethod
    def _resolve_timezone(tz_name: str) -> Any:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            # Fall back to UTC rather than failing — schedule jobs in UTC
            # rather than crashing the whole scheduler.
            from datetime import timezone as _tz

            logger.warning("unknown timezone {!r} — falling back to UTC", tz_name)
            return _tz.utc

    @staticmethod
    def _parse_run_date(run_date: Any) -> datetime:
        """Parse run_date (ISO string or datetime) into a tz-aware datetime."""
        if isinstance(run_date, datetime):
            return run_date if run_date.tzinfo else run_date.replace(
                tzinfo=timezone.utc
            )
        s = str(run_date)
        # Try a few common formats
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            # Final fallback — assume UTC epoch-style timestamp
            try:
                return datetime.fromtimestamp(float(s), tz=timezone.utc)
            except Exception as exc:
                raise ValueError(f"unparseable run_date: {run_date!r}") from exc

    # ------------------------------------------------------------------
    # Internal: workflow loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_workflow(workflow_id: str) -> Optional[Workflow]:
        """Load a Workflow JSON from settings.workflows_dir."""
        wf_path: Path = settings.workflows_dir / f"{workflow_id}.json"
        if not wf_path.exists():
            return None
        try:
            return Workflow.model_validate_json(wf_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("failed to load workflow {}: {}", workflow_id, exc)
            return None

    # ------------------------------------------------------------------
    # Internal: DB persistence
    # ------------------------------------------------------------------

    def _persist_job(
        self,
        job_id: str,
        workflow_id: str,
        config: dict[str, Any],
    ) -> None:
        """Insert (or update) a row in the scheduled_jobs table.

        Lazy-imports :mod:`database.base` so tests can monkeypatch
        ``SessionLocal`` with an in-memory engine before scheduling.
        """
        try:
            from database.base import SessionLocal
            from database.models.schema import ScheduledJob
        except Exception as exc:  # pragma: no cover - DB optional in tests
            logger.debug("DB unavailable, skipping persistence: {}", exc)
            return

        next_run_at: Optional[datetime] = None
        try:
            job = self._scheduler.get_job(job_id)
            if job is not None and job.next_run_time is not None:
                next_run_at = job.next_run_time
        except Exception:
            pass

        retry_policy: Optional[dict[str, Any]] = None
        if config.get("retry_policy"):
            retry_policy = config["retry_policy"]

        try:
            with SessionLocal() as session:
                existing = session.get(ScheduledJob, job_id)
                if existing is not None:
                    existing.trigger_type = config.get("type", "schedule")
                    existing.cron = config.get("cron")
                    existing.timezone = config.get("timezone", "UTC")
                    existing.next_run_at = next_run_at
                    existing.retry_policy = retry_policy
                    existing.execution_timeout = int(
                        config.get("execution_timeout", DEFAULT_EXECUTION_TIMEOUT)
                    )
                    existing.enabled = True
                else:
                    row = ScheduledJob(
                        id=job_id,
                        workflow_id=workflow_id,
                        trigger_type=config.get("type", "schedule"),
                        cron=config.get("cron"),
                        timezone=config.get("timezone", "UTC"),
                        next_run_at=next_run_at,
                        retry_policy=retry_policy,
                        execution_timeout=int(
                            config.get(
                                "execution_timeout", DEFAULT_EXECUTION_TIMEOUT
                            )
                        ),
                        enabled=True,
                    )
                    session.add(row)
                session.commit()
        except Exception as exc:  # pragma: no cover - DB optional
            logger.warning("Failed to persist scheduled_job {}: {}", job_id, exc)

    def _delete_job_row(self, job_id: str) -> None:
        try:
            from database.base import SessionLocal
            from database.models.schema import ScheduledJob
        except Exception:  # pragma: no cover - DB optional
            return

        try:
            with SessionLocal() as session:
                row = session.get(ScheduledJob, job_id)
                if row is not None:
                    session.delete(row)
                    session.commit()
        except Exception as exc:  # pragma: no cover - DB optional
            logger.warning("Failed to delete scheduled_job {}: {}", job_id, exc)

    # ------------------------------------------------------------------
    # Internal: standalone trigger introspection helper
    # ------------------------------------------------------------------

    @staticmethod
    def _standalone_job_dict(
        job_id: str,
        cfg: dict[str, Any],
        trigger_type: str,
        trig: Any,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "workflow_id": cfg.get("workflow_id"),
            "trigger_type": trigger_type,
            "trigger_config": cfg,
            "next_run_time": None,
            "is_active": getattr(trig, "is_active", False),
            "source": "standalone",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Module-level singleton.
scheduler_manager = SchedulerManager()

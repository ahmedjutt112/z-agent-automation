"""OSAssistantAgent — master prompt §83 (Phase 5 — Advanced AI OS Assistant).

A high-level orchestration layer above the existing PlannerAgent. The
assistant exposes contextual, multi-step automation goals like:

- ``prepare_for_meeting(meeting_id=None)`` — fetch the next meeting from
  the calendar, look up the user's preferred apps / browser / notes via
  MemoryManager, and generate a Plan that opens the agenda, related tabs,
  notes app, presentation, and a meeting dashboard. The Plan is returned
  WITHOUT executing — the user must approve per §66 before it runs.
- ``organize_files_by_context(context)`` — generate a file-organisation
  Plan (project, date range, attendees) WITHOUT executing.
- ``morning_routine()`` — open mail, calendar, today's tasks.
- ``end_of_day_summary()`` — return a summary of the day's automation
  activities (no plan, just a dict).
- ``research_topic(topic, depth=3)`` — generate a research Plan that opens
  browser tabs, runs web searches, and saves findings.

CRITICAL (master prompt §83): every external action MUST still pass
through the permission engine and user-defined policies. This agent never
auto-executes plans — it always returns the Plan and lets the caller (the
FastAPI router / voice pipeline / desktop renderer) decide whether to run
it via the WorkflowExecutor after explicit user approval.

All methods use MemoryManager.get_context_for_planner() to personalise
the generated Plan (preferred browser, preferred notes app, etc.). When
no memory exists yet, sensible defaults are used.

When ``settings.mock_mode`` is True (the default in dev / tests), every
method returns a deterministic fake Plan so the desktop renderer can be
demoed without a live AI provider.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.event_bus import event_bus
from ..integrations.calendar import (
    CalendarEvent,
    CalendarService,
    MockCalendarService,
    get_calendar_service,
)
from ..models import (
    PermissionLevel,
    Plan,
    PlanStep,
    RiskLevel,
)
from ..memory.manager import MemoryManager, MemoryType
from .planner import PlannerAgent


# ---------------------------------------------------------------------------
# Pydantic models for assistant outputs
# ---------------------------------------------------------------------------


class MeetingPreparation(BaseModel):
    """Result of :meth:`OSAssistantAgent.prepare_for_meeting`.

    The Plan is returned but NOT executed (master prompt §66 — every
    external action requires explicit user approval first).
    """

    plan: Plan
    meeting: CalendarEvent
    opened_apps: list[str] = Field(default_factory=list)
    opened_tabs: list[str] = Field(default_factory=list)
    organized_files: list[str] = Field(default_factory=list)
    dashboard_url: Optional[str] = None


# ---------------------------------------------------------------------------
# OSAssistantAgent
# ---------------------------------------------------------------------------


class OSAssistantAgent:
    """Phase 5 — Advanced AI OS Assistant (master prompt §83).

    A high-level agent that composes plans from natural-language intents
    like "prepare everything for my 9 AM meeting". Each method returns a
    Plan WITHOUT executing it — the caller is responsible for surfacing
    the plan to the user and explicitly approving it before passing it to
    the WorkflowExecutor (master prompt §66).
    """

    def __init__(
        self,
        planner_agent: Optional[PlannerAgent] = None,
        memory: Optional[MemoryManager] = None,
        calendar: Optional[CalendarService] = None,
    ) -> None:
        self._planner = planner_agent or PlannerAgent()
        self._memory = memory or MemoryManager()
        # Calendar is resolved lazily via the factory so the agent picks
        # up mock vs google automatically based on settings.mock_mode.
        self._calendar = calendar or get_calendar_service()
        self._mock_mode = settings.mock_mode

    # ------------------------------------------------------------------
    # prepare_for_meeting — master prompt §83 example
    # ------------------------------------------------------------------

    async def prepare_for_meeting(
        self, meeting_id: Optional[str] = None
    ) -> MeetingPreparation:
        """Generate a multi-step meeting-prep Plan.

        Steps generated (in order):
        1. Open the meeting agenda document (if attached).
        2. Open browser tabs for the meeting link + related docs.
        3. Launch the user's preferred notes app.
        4. Open the presentation file (if attached).
        5. Organise files related to attendees into a "Meeting Prep" folder.
        6. Show a "Meeting Dashboard" view with all open items.

        Returns the Plan + context WITHOUT executing it. The user must
        approve per §66 before the WorkflowExecutor runs it.
        """
        if meeting_id is not None:
            meeting = await self._calendar.get_event(meeting_id)
        else:
            meeting = await self._calendar.get_next_meeting()
            if meeting is None:
                # No upcoming meetings — return an empty plan that records
                # the situation so the caller can surface it.
                empty = self._empty_plan("No upcoming meetings to prepare for.")
                return MeetingPreparation(
                    plan=empty,
                    meeting=CalendarEvent(
                        id="none",
                        title="(no upcoming meeting)",
                        start_at=datetime.now(timezone.utc),
                        end_at=datetime.now(timezone.utc),
                    ),
                )

        # Personalise via memory — preferred browser / notes app / etc.
        ctx = await self._memory.get_context_for_planner()
        preferred_browser = self._pref(ctx, "preferred_browser", settings.browser_default)
        preferred_notes_app = self._pref(ctx, "preferred_notes_app", "obsidian")

        steps: list[PlanStep] = []

        # 1. Open the agenda document (if attached).
        agenda_url = (meeting.metadata or {}).get("agenda_url")
        if agenda_url:
            steps.append(
                PlanStep(
                    id="1",
                    action="browser.open",
                    args={"url": agenda_url, "browser": preferred_browser},
                    risk_level=RiskLevel.LOW,
                    confidence=0.9,
                    verification="browser_tab_opened",
                )
            )

        # 2. Open meeting link + related tabs.
        meeting_url = meeting.meeting_link or meeting.conference_url or meeting.location
        tabs_to_open: list[str] = []
        if meeting_url:
            tabs_to_open.append(meeting_url)
        for att in meeting.attendees:
            if att.email:
                # Open a quick LinkedIn / lookup tab per attendee —
                # this is a mock; the real planner would decide.
                tabs_to_open.append(f"https://www.linkedin.com/search/results/people/?keywords={att.email}")
        for tab_url in tabs_to_open[: settings.max_browser_tabs]:
            steps.append(
                PlanStep(
                    id=f"tab-{len(steps) + 1}",
                    action="browser.open",
                    args={"url": tab_url, "browser": preferred_browser},
                    risk_level=RiskLevel.LOW,
                    confidence=0.85,
                    verification="browser_tab_opened",
                )
            )

        # 3. Launch the user's preferred notes app.
        steps.append(
            PlanStep(
                id="notes",
                action="app.launch",
                args={"app": preferred_notes_app},
                risk_level=RiskLevel.LOW,
                confidence=0.95,
                verification="process_running",
            )
        )

        # 4. Open the presentation file (if attached).
        presentation_path = (meeting.metadata or {}).get("presentation_path")
        if presentation_path:
            steps.append(
                PlanStep(
                    id="presentation",
                    action="app.launch",
                    args={"app": "powerpoint", "file": presentation_path},
                    risk_level=RiskLevel.LOW,
                    confidence=0.9,
                    verification="process_running",
                )
            )

        # 5. Organise files related to attendees into a "Meeting Prep" folder.
        prep_folder = f"/home/z/Meeting_Prep/{meeting.id}"
        steps.append(
            PlanStep(
                id="organize",
                action="file.move",
                args={
                    "destination": prep_folder,
                    "pattern": " ".join(
                        a.name or a.email or "" for a in meeting.attendees
                    ).strip(),
                },
                risk_level=RiskLevel.MEDIUM,
                confidence=0.75,
                fallback="screen.ocr",
                verification="folder_exists",
            )
        )

        # 6. Show a "Meeting Dashboard" view.
        dashboard_url = f"http://localhost:5173/#/meeting-dashboard/{meeting.id}"
        steps.append(
            PlanStep(
                id="dashboard",
                action="browser.open",
                args={"url": dashboard_url, "browser": preferred_browser},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="browser_tab_opened",
            )
        )

        plan = Plan(
            id=uuid4(),
            goal=f"Prepare everything for the {meeting.title} meeting at {meeting.start_at.isoformat()}",
            steps=steps,
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.MEDIUM,
            potential_side_effects=[
                "opens multiple browser tabs",
                "launches external applications",
                "creates a Meeting_Prep folder",
            ],
            estimated_duration_seconds=20,
            variables={
                "meeting_id": meeting.id,
                "meeting_title": meeting.title,
                "preferred_browser": preferred_browser,
                "preferred_notes_app": preferred_notes_app,
                "dashboard_url": dashboard_url,
            },
        )

        event_bus.publish(
            "TASK_CREATED",
            {
                "plan_id": str(plan.id),
                "goal": plan.goal,
                "source": "os_assistant.prepare_for_meeting",
                "meeting_id": meeting.id,
            },
        )

        return MeetingPreparation(
            plan=plan,
            meeting=meeting,
            opened_apps=[preferred_notes_app] + (["powerpoint"] if presentation_path else []),
            opened_tabs=tabs_to_open,
            organized_files=[prep_folder],
            dashboard_url=dashboard_url,
        )

    # ------------------------------------------------------------------
    # organize_files_by_context
    # ------------------------------------------------------------------

    async def organize_files_by_context(self, context: dict[str, Any]) -> Plan:
        """Generate a file-organisation Plan based on context.

        ``context`` may include:
        - ``project`` (str): project name to filter files by.
        - ``date_range`` (dict): {"start": ISO, "end": ISO} for file mtime.
        - ``attendees`` (list[str]): file names / patterns related to attendees.
        - ``destination`` (str): target folder (default: /home/z/Organized/<project>).
        """
        project = context.get("project", "general")
        attendees = context.get("attendees", []) or []
        date_range = context.get("date_range", {}) or {}
        destination = context.get("destination", f"/home/z/Organized/{project}")

        ctx = await self._memory.get_context_for_planner()
        preferred_browser = self._pref(ctx, "preferred_browser", settings.browser_default)

        steps: list[PlanStep] = [
            PlanStep(
                id="mkdir",
                action="file.write",
                args={"path": destination + "/.folder_marker", "content": "auto-organised"},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="folder_exists",
            ),
            PlanStep(
                id="list",
                action="file.list",
                args={
                    "directory": "/home/z",
                    "pattern": project,
                    "since": date_range.get("start"),
                    "until": date_range.get("end"),
                },
                risk_level=RiskLevel.LOW,
                confidence=0.95,
                verification="list_returned",
            ),
            PlanStep(
                id="move",
                action="file.move",
                args={
                    "destination": destination,
                    "pattern": " ".join(attendees) if attendees else project,
                    "since": date_range.get("start"),
                },
                risk_level=RiskLevel.MEDIUM,
                confidence=0.8,
                fallback="screen.ocr",
                verification="files_moved",
            ),
            PlanStep(
                id="open_folder",
                action="browser.open",
                args={"url": f"file://{destination}", "browser": preferred_browser},
                risk_level=RiskLevel.LOW,
                confidence=0.95,
                verification="browser_tab_opened",
            ),
        ]

        return Plan(
            id=uuid4(),
            goal=f"Organise files for project '{project}' into {destination}",
            steps=steps,
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.MEDIUM,
            potential_side_effects=["moves files between directories"],
            estimated_duration_seconds=15,
            variables={
                "project": str(project),
                "destination": destination,
                "attendees_count": str(len(attendees)),
            },
        )

    # ------------------------------------------------------------------
    # morning_routine
    # ------------------------------------------------------------------

    async def morning_routine(self) -> Plan:
        """Open mail, calendar, and today's tasks.

        The user is expected to approve the Plan before it runs (§66).
        """
        ctx = await self._memory.get_context_for_planner()
        preferred_browser = self._pref(ctx, "preferred_browser", settings.browser_default)
        preferred_mail_app = self._pref(ctx, "preferred_mail_app", "outlook")

        steps = [
            PlanStep(
                id="mail",
                action="app.launch",
                args={"app": preferred_mail_app},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="process_running",
            ),
            PlanStep(
                id="calendar",
                action="browser.open",
                args={"url": "https://calendar.google.com", "browser": preferred_browser},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="browser_tab_opened",
            ),
            PlanStep(
                id="tasks",
                action="browser.open",
                args={"url": "http://localhost:5173/#/tasks", "browser": preferred_browser},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="browser_tab_opened",
            ),
            PlanStep(
                id="screenshot",
                action="screen.capture",
                args={"filename": "morning_routine_dashboard.png"},
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="file_exists",
            ),
        ]

        return Plan(
            id=uuid4(),
            goal="Morning routine — open mail, calendar, and today's tasks",
            steps=steps,
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.LOW,
            potential_side_effects=["opens 3 windows / tabs"],
            estimated_duration_seconds=10,
            variables={
                "preferred_browser": preferred_browser,
                "preferred_mail_app": preferred_mail_app,
            },
        )

    # ------------------------------------------------------------------
    # end_of_day_summary — returns a dict, NOT a Plan
    # ------------------------------------------------------------------

    async def end_of_day_summary(self) -> dict[str, Any]:
        """Return a summary of the day's automation activities.

        Reads recent workflow / task memories and counts today's runs.
        In mock mode, returns a deterministic summary.
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Recent workflow memory — count today's entries.
        workflows = await self._memory.recall(MemoryType.WORKFLOW)
        today_workflows = [w for w in workflows if w.created_at >= today_start]
        tasks = await self._memory.recall(MemoryType.TASK_CONTEXT)
        today_tasks = [t for t in tasks if t.created_at >= today_start]

        summary: dict[str, Any] = {
            "date": today_start.date().isoformat(),
            "total_runs": len(today_workflows),
            "total_tasks": len(today_tasks),
            "highlights": [
                {"key": w.key, "value": w.value, "at": w.created_at.isoformat()}
                for w in today_workflows[:5]
            ],
            "task_context": [
                {"key": t.key, "value": t.value, "at": t.created_at.isoformat()}
                for t in today_tasks[:5]
            ],
            "next_meeting": None,
        }

        # Surface the next upcoming meeting too.
        try:
            nxt = await self._calendar.get_next_meeting()
            if nxt is not None:
                summary["next_meeting"] = {
                    "title": nxt.title,
                    "start_at": nxt.start_at.isoformat(),
                    "meeting_link": nxt.meeting_link,
                }
        except Exception as exc:
            logger.debug("end_of_day_summary: calendar lookup failed: {}", exc)

        # Mock-mode flavour so the desktop renderer always has something to show.
        if self._mock_mode and not today_workflows:
            summary["mock_mode"] = True
            summary["highlights"] = [
                {
                    "key": "demo_run",
                    "value": "No automation runs today (mock mode).",
                    "at": now.isoformat(),
                }
            ]

        event_bus.publish(
            "TASK_COMPLETED",
            {"source": "os_assistant.end_of_day_summary", "summary_runs": summary["total_runs"]},
        )
        return summary

    # ------------------------------------------------------------------
    # research_topic
    # ------------------------------------------------------------------

    async def research_topic(self, topic: str, depth: int = 3) -> Plan:
        """Generate a research Plan that opens browser tabs + web searches.

        ``depth`` controls how many sub-queries / tabs to open (1-5).
        """
        depth = max(1, min(5, int(depth)))
        ctx = await self._memory.get_context_for_planner()
        preferred_browser = self._pref(ctx, "preferred_browser", settings.browser_default)

        queries: list[str] = [f"{topic} overview", f"{topic} latest research {now_year()}"]
        if depth >= 3:
            queries.append(f"{topic} comparison alternatives")
        if depth >= 4:
            queries.append(f"{topic} tutorials")
        if depth >= 5:
            queries.append(f"{topic} academic papers")

        steps: list[PlanStep] = []
        for i, q in enumerate(queries[:depth]):
            steps.append(
                PlanStep(
                    id=f"search-{i + 1}",
                    action="browser.open",
                    args={
                        "url": f"https://www.google.com/search?q={q.replace(' ', '+')}",
                        "browser": preferred_browser,
                    },
                    risk_level=RiskLevel.LOW,
                    confidence=0.95,
                    verification="browser_tab_opened",
                )
            )
        # Save findings to a notes file.
        findings_path = f"/home/z/Research/{topic.replace(' ', '_')[:40]}/findings.md"
        steps.append(
            PlanStep(
                id="save-findings",
                action="file.write",
                args={
                    "path": findings_path,
                    "content": f"# Research findings: {topic}\n\nGenerated by OSAssistantAgent.\n",
                },
                risk_level=RiskLevel.LOW,
                confidence=1.0,
                verification="file_exists",
            )
        )

        return Plan(
            id=uuid4(),
            goal=f"Research '{topic}' (depth {depth}) — open browser tabs, run web searches, save findings",
            steps=steps,
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.LOW,
            potential_side_effects=["opens up to 5 browser tabs", "creates a Research folder"],
            estimated_duration_seconds=10 * depth,
            variables={
                "topic": topic,
                "depth": str(depth),
                "findings_path": findings_path,
                "preferred_browser": preferred_browser,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_plan(self, goal: str) -> Plan:
        """Return a no-step Plan — used when there's nothing to do."""
        return Plan(
            id=uuid4(),
            goal=goal,
            steps=[],
            required_permissions=[PermissionLevel.ALLOW_ONCE],
            overall_risk=RiskLevel.LOW,
            potential_side_effects=[],
            estimated_duration_seconds=0,
            variables={"empty": "true"},
        )

    @staticmethod
    def _pref(ctx: dict, key: str, default: str) -> str:
        """Pull a preference out of MemoryManager.get_context_for_planner()."""
        for entry in ctx.get("user_preferences", []):
            if entry.get("key") == key:
                v = entry.get("value")
                if isinstance(v, str) and v:
                    return v
        return default


# ---------------------------------------------------------------------------
# Module-level singleton — mirrors memory_manager / scheduler_manager / etc.
# ---------------------------------------------------------------------------


def now_year() -> int:
    """Tiny helper so the research_topic default queries are year-aware."""
    return datetime.now(timezone.utc).year


os_assistant = OSAssistantAgent()


__all__ = [
    "MeetingPreparation",
    "OSAssistantAgent",
    "os_assistant",
]

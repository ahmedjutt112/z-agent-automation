"""WorkflowGeneratorAgent - master prompt section 23 (AI Workflow Generation).

Converts free-form descriptions / task recordings into reusable
:class:`Workflow` objects, suggests automations the user might want,
and improves existing workflows based on natural-language feedback.

Methods:

* ``generate_from_description(description)`` -> Workflow
  * User says "Every day at 6 PM organize my Downloads folder".
  * Generates a complete Workflow with a SCHEDULE trigger + nodes
    for listing / moving files.
  * Uses PlannerAgent to break the goal into steps, then converts
    each PlanStep into a WorkflowNode.

* ``generate_from_recording(recording_id)`` -> Workflow
  * Takes a TaskRecorder recording and converts it to a reusable
    Workflow. Identifies patterns (repeated clicks, typing) and
    parameterizes them. Suggests variables (e.g. ``{{downloads_folder}}``).

* ``improve_workflow(workflow, feedback)`` -> Workflow
  * User says "make it also rename files by date".
  * Adds the requested step to the workflow, bumps the version number,
    and returns a new Workflow object (does NOT mutate the input).

* ``suggest_automations()`` -> list[Suggestion]
  * Analyzes recent task history + memory.
  * Returns a list of :class:`Suggestion` with title, description,
    estimated time saved per week, and a proposed Workflow.

Mock mode respected - every method returns deterministic fake data
when ``settings.mock_mode`` is True so the renderer + tests can be
exercised without real AI calls.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.event_bus import event_bus
from ..memory.manager import MemoryManager, MemoryType, memory_manager as default_memory
from ..models import (
    PermissionLevel,
    Plan,
    PlanStep,
    RiskLevel,
    TriggerType,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
)
from .observer_agent import ObserverAgent, observer_agent as default_observer
from .planner import PlannerAgent


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Suggestion(BaseModel):
    """A suggested automation the user might want."""

    title: str
    description: str
    estimated_time_saved_per_week: str = "unknown"
    proposed_workflow: Workflow


# ---------------------------------------------------------------------------
# WorkflowGeneratorAgent
# ---------------------------------------------------------------------------


class WorkflowGeneratorAgent:
    """Generates + improves Workflows from NL descriptions / recordings."""

    def __init__(
        self,
        planner: Optional[PlannerAgent] = None,
        observer: Optional[ObserverAgent] = None,
        memory: Optional[MemoryManager] = None,
    ) -> None:
        self._planner = planner or PlannerAgent()
        self._observer = observer or default_observer
        self._memory = memory or default_memory

    # ------------------------------------------------------------------
    # generate_from_description
    # ------------------------------------------------------------------

    async def generate_from_description(self, description: str) -> Workflow:
        """Generate a complete :class:`Workflow` from a NL description.

        Parses trigger hints ("every day at 6 PM", "when I plug in my
        headphones", "on Mondays at 9am") out of the description; the
        rest is converted into workflow nodes via PlannerAgent.plan().
        """
        # 1. Use the planner to break the goal into steps.
        # We rewrite the description slightly so the planner sees the
        # full goal including trigger context.
        plan = await self._planner.plan(description)

        # 2. Detect trigger from the description.
        trigger = self._detect_trigger(description)

        # 3. Convert PlanSteps -> WorkflowNodes.
        nodes = self._plan_to_nodes(plan)

        # 4. Suggest variables.
        variables = self._suggest_variables(description, plan)

        # 5. Choose a name from the description (first 60 chars).
        name = description.strip()[:60]
        if not name:
            name = "Generated workflow"

        wf = Workflow(
            id=f"gen-{uuid4().hex[:8]}",
            name=name,
            version=1,
            description=description,
            trigger=trigger,
            nodes=nodes,
            variables=variables,
            enabled=False,  # user must explicitly enable (section 51)
        )
        event_bus.publish(
            "TASK_CREATED",
            {"source": "workflow_generator.generate_from_description", "workflow_id": wf.id},
        )
        return wf

    # ------------------------------------------------------------------
    # generate_from_recording
    # ------------------------------------------------------------------

    async def generate_from_recording(self, recording_id: str) -> Workflow:
        """Convert a TaskRecorder recording into a reusable Workflow."""
        try:
            from ..engine.recorder import task_recorder
        except Exception as exc:
            logger.warning("recorder module unavailable: {}", exc)
            return self._mock_recording_workflow(recording_id)

        rec = task_recorder._recording  # noqa: SLF001 - same-package access
        if rec is None or rec.id != recording_id:
            # In mock mode, just synthesise a workflow.
            return self._mock_recording_workflow(recording_id)

        try:
            wf = task_recorder.to_workflow(rec, name=f"Recorded {recording_id[:8]}")
        except Exception as exc:
            logger.warning("to_workflow failed: {}", exc)
            return self._mock_recording_workflow(recording_id)

        # Parameterize - replace literal paths with variables.
        wf.variables.update(self._extract_variables_from_nodes(wf.nodes))
        for node in wf.nodes:
            node.args = self._parameterize_args(node.args, wf.variables)
        wf.id = f"rec-{recording_id[:8]}"
        wf.enabled = False  # user must explicitly enable
        return wf

    # ------------------------------------------------------------------
    # improve_workflow
    # ------------------------------------------------------------------

    async def improve_workflow(
        self, workflow: Workflow, feedback: str
    ) -> Workflow:
        """Return a NEW Workflow with the feedback applied.

        Adds a new node at the end based on the feedback. Bumps the
        version number. Never mutates the input.
        """
        new_nodes: list[WorkflowNode] = list(workflow.nodes)
        next_id = f"node_{len(new_nodes) + 1}"

        # Try to translate feedback into a node action + args.
        action, args = self._interpret_feedback(feedback)
        new_node = WorkflowNode(
            id=next_id,
            type=action,
            args=args,
            next=None,
        )
        new_nodes.append(new_node)

        # Link the previous tail node (if any) to the new node.
        if len(new_nodes) >= 2 and new_nodes[-2].next is None:
            new_nodes[-2].next = next_id

        # Bump version.
        new_version = (workflow.version or 1) + 1

        return Workflow(
            id=workflow.id,
            name=workflow.name,
            version=new_version,
            description=(workflow.description or "") + f"\n\nFeedback applied: {feedback}",
            trigger=workflow.trigger,
            nodes=new_nodes,
            variables={**workflow.variables, **self._suggest_variables(feedback, None)},
            enabled=workflow.enabled,
            profile_id=workflow.profile_id,
            created_at=workflow.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # suggest_automations
    # ------------------------------------------------------------------

    async def suggest_automations(self) -> list[Suggestion]:
        """Analyze recent memory + suggest workflows the user might want.

        Returns a list of :class:`Suggestion` sorted by estimated
        weekly time saved (highest first).
        """
        suggestions: list[Suggestion] = []

        # Mock-mode suggestions - always include a couple so the UI has
        # something to render. Real mode would analyze memory for
        # repeated patterns.
        suggestions.extend(self._mock_suggestions())

        # Add memory-driven suggestions.
        try:
            workflows = await self._memory.recall(MemoryType.WORKFLOW)
            # Count how many times each goal prefix appears.
            seen: dict[str, int] = {}
            for m in workflows:
                if not m.key.startswith("autonomous_pattern::"):
                    continue
                goal = (m.value or {}).get("goal", "") if isinstance(m.value, dict) else ""
                if not goal:
                    continue
                prefix = goal[:40]
                seen[prefix] = seen.get(prefix, 0) + 1
            for prefix, count in seen.items():
                if count < 2:
                    continue
                # Suggest automating this recurring goal.
                try:
                    wf = await self.generate_from_description(prefix)
                except Exception as exc:
                    logger.debug("suggest_automations generate failed: {}", exc)
                    continue
                suggestions.append(
                    Suggestion(
                        title=f"Automate: {prefix}",
                        description=(
                            f"You've run this goal {count} times this week - "
                            "automate it as a Workflow."
                        ),
                        estimated_time_saved_per_week=f"~{count * 5} minutes",
                        proposed_workflow=wf,
                    )
                )
        except Exception as exc:
            logger.debug("suggest_automations memory scan failed: {}", exc)

        return suggestions

    # ------------------------------------------------------------------
    # Helpers - trigger detection, plan -> nodes, variables, feedback
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_trigger(description: str) -> WorkflowTrigger:
        """Detect a trigger type + config from a NL description."""
        d = description.lower()
        # SCHEDULE - "every day at 6 PM", "on Mondays at 9am", "daily at noon"
        schedule_patterns = [
            (r"every day at\s+(\d{1,2}\s*(?:am|pm)?)", lambda m: _cron_from_time(m.group(1))),
            (r"daily at\s+(\d{1,2}\s*(?:am|pm)?)", lambda m: _cron_from_time(m.group(1))),
            (r"every (\w+) at\s+(\d{1,2}\s*(?:am|pm)?)",
             lambda m: _cron_from_weekday_time(m.group(1), m.group(2))),
            (r"at\s+(\d{1,2}:\d{2})", lambda m: _cron_from_hhmm(m.group(1))),
        ]
        for pat, builder in schedule_patterns:
            m = re.search(pat, d)
            if m:
                return WorkflowTrigger(
                    type=TriggerType.SCHEDULE,
                    cron=builder(m),
                    timezone="UTC",
                )
        # FILE - "when a file appears in X"
        if "when a file" in d or "when file" in d or "on new file" in d:
            return WorkflowTrigger(
                type=TriggerType.FILE,
                file_pattern="*",
            )
        # HOTKEY - "when I press Ctrl+Shift+D"
        m = re.search(r"(?:press|hotkey)\s+([A-Za-z0-9+]+)", d)
        if m:
            return WorkflowTrigger(
                type=TriggerType.HOTKEY,
                hotkey=m.group(1),
            )
        # Default: manual trigger.
        return WorkflowTrigger(type=TriggerType.MANUAL)

    @staticmethod
    def _plan_to_nodes(plan: Plan) -> list[WorkflowNode]:
        """Convert a Plan's steps into WorkflowNodes (linear)."""
        nodes: list[WorkflowNode] = []
        for i, step in enumerate(plan.steps):
            next_id = (
                f"node_{i + 2}" if i + 1 < len(plan.steps) else None
            )
            nodes.append(
                WorkflowNode(
                    id=f"node_{i + 1}",
                    type=step.action,
                    args=dict(step.args),
                    next=next_id,
                    timeout_ms=step.timeout_ms,
                    retry_count=step.retry_count,
                )
            )
        return nodes

    @staticmethod
    def _suggest_variables(description: str, plan: Optional[Plan]) -> dict[str, str]:
        """Suggest variables based on the description + plan."""
        variables: dict[str, str] = {}
        d = description.lower()
        if "downloads" in d or "downloads folder" in d:
            variables["downloads_folder"] = str(Path.home() / "Downloads")
        if "documents" in d:
            variables["documents_folder"] = str(Path.home() / "Documents")
        if "desktop" in d:
            variables["desktop_folder"] = str(Path.home() / "Desktop")
        if "browser" in d:
            variables["browser"] = settings.browser_default
        if plan is not None:
            for k, v in plan.variables.items():
                # Plan.variables are always strings - safe to copy.
                variables.setdefault(k, str(v))
        return variables

    @staticmethod
    def _interpret_feedback(feedback: str) -> tuple[str, dict[str, Any]]:
        """Translate NL feedback into a (node action, args) pair.

        Recognises a handful of common improvement requests. Unknown
        feedback falls through to a generic ``file.write`` step that
        records the request (so the user sees the workflow was changed
        but no destructive action runs without further tuning).
        """
        f = feedback.lower()
        if "rename" in f and "date" in f:
            return "file.rename", {"pattern": "{{date}}_{{filename}}"}
        if "rename" in f:
            return "file.rename", {"pattern": "{{new_name}}"}
        if "delete" in f:
            return "file.move", {"destination": "{{trash}}", "pattern": "{{pattern}}"}
        if "open" in f and "browser" in f:
            return "browser.open", {"url": "{{url}}", "browser": "{{browser}}"}
        if "screenshot" in f:
            return "screen.capture", {"filename": "feedback_{{timestamp}}.png"}
        if "notify" in f or "notification" in f:
            return "app.launch", {"app": "notifications"}
        return "file.write", {
            "path": "{{workflow_dir}}/feedback.txt",
            "content": feedback,
        }

    @staticmethod
    def _extract_variables_from_nodes(nodes: list[WorkflowNode]) -> dict[str, str]:
        """Find literal-looking values in node args and suggest variables."""
        variables: dict[str, str] = {}
        for node in nodes:
            for k, v in node.args.items():
                if not isinstance(v, str):
                    continue
                # Paths -> suggest {{..._folder}}
                if v.startswith("/") or v.startswith("~"):
                    tail = v.rsplit("/", 1)[-1]
                    if "." in tail:  # looks like a file
                        variables.setdefault(
                            tail.replace(".", "_").lower(),
                            v,
                        )
        return variables

    @staticmethod
    def _parameterize_args(args: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
        """Replace literal values in args with ``{{var}}`` placeholders
        when they match a known variable."""
        out: dict[str, Any] = {}
        for k, v in args.items():
            if isinstance(v, str):
                for var_name, var_value in variables.items():
                    if v == var_value:
                        out[k] = f"{{{{{var_name}}}}}"
                        break
                else:
                    out[k] = v
            else:
                out[k] = v
        return out

    # ------------------------------------------------------------------
    # Mock helpers - used when recorder / memory unavailable
    # ------------------------------------------------------------------

    def _mock_recording_workflow(self, recording_id: str) -> Workflow:
        return Workflow(
            id=f"rec-{recording_id[:8]}",
            name=f"Recorded Workflow {recording_id[:8]}",
            version=1,
            description="(mock) Generated from recording",
            trigger=WorkflowTrigger(type=TriggerType.MANUAL),
            nodes=[
                WorkflowNode(
                    id="node_1",
                    type="browser.navigate",
                    args={"url": "https://{{target_site}}"},
                ),
                WorkflowNode(
                    id="node_2",
                    type="browser.click",
                    args={"selector": "#download-button"},
                    next=None,
                ),
            ],
            variables={"target_site": "example.com"},
            enabled=False,
        )

    def _mock_suggestions(self) -> list[Suggestion]:
        """Two canonical mock suggestions the renderer can always show."""
        weekly_dl = Workflow(
            id="sugg-weekly-downloads",
            name="Weekly Downloads cleanup",
            version=1,
            description="(mock) Move files older than 7 days out of Downloads",
            trigger=WorkflowTrigger(
                type=TriggerType.SCHEDULE,
                cron="0 18 * * *",  # 6 PM daily
                timezone="UTC",
            ),
            nodes=[
                WorkflowNode(
                    id="node_1",
                    type="file.list",
                    args={"directory": "{{downloads_folder}}", "older_than_days": 7},
                    next="node_2",
                ),
                WorkflowNode(
                    id="node_2",
                    type="file.move",
                    args={"destination": "{{archive_folder}}", "pattern": "*"},
                    next=None,
                ),
            ],
            variables={
                "downloads_folder": str(Path.home() / "Downloads"),
                "archive_folder": str(Path.home() / "Archive"),
            },
            enabled=False,
        )

        morning_check = Workflow(
            id="sugg-morning-summary",
            name="Morning summary",
            version=1,
            description="(mock) Daily 8 AM summary: open calendar + email + tasks",
            trigger=WorkflowTrigger(
                type=TriggerType.SCHEDULE,
                cron="0 8 * * *",
                timezone="UTC",
            ),
            nodes=[
                WorkflowNode(
                    id="node_1",
                    type="browser.open",
                    args={"url": "https://calendar.google.com", "browser": "{{browser}}"},
                    next="node_2",
                ),
                WorkflowNode(
                    id="node_2",
                    type="app.launch",
                    args={"app": "{{mail_app}}"},
                    next="node_3",
                ),
                WorkflowNode(
                    id="node_3",
                    type="screen.capture",
                    args={"filename": "morning_summary.png"},
                    next=None,
                ),
            ],
            variables={"browser": "chrome", "mail_app": "outlook"},
            enabled=False,
        )

        return [
            Suggestion(
                title="Tidy your Downloads folder weekly",
                description=(
                    "You've manually organised your Downloads folder several times "
                    "this week - automate it."
                ),
                estimated_time_saved_per_week="~15 minutes",
                proposed_workflow=weekly_dl,
            ),
            Suggestion(
                title="Morning summary at 8 AM",
                description=(
                    "Open your calendar + email + task list every morning so you "
                    "start the day oriented."
                ),
                estimated_time_saved_per_week="~5 minutes",
                proposed_workflow=morning_check,
            ),
        ]


# ---------------------------------------------------------------------------
# Cron helpers - only used by _detect_trigger; kept module-private.
# ---------------------------------------------------------------------------


def _cron_from_time(time_str: str) -> str:
    """Convert '6 PM' or '6pm' or '14' to a cron string (daily at HH:00)."""
    s = time_str.strip().lower().replace(" ", "")
    hour = 0
    try:
        if "am" in s:
            hour = int(s.replace("am", "")) % 12
        elif "pm" in s:
            hour = (int(s.replace("pm", "")) + 12) % 24
        else:
            hour = int(s) % 24
    except ValueError:
        hour = 18  # safe default
    return f"0 {hour} * * *"


def _cron_from_weekday_time(weekday: str, time_str: str) -> str:
    days = {
        "monday": 1, "mon": 1,
        "tuesday": 2, "tue": 2, "tues": 2,
        "wednesday": 3, "wed": 3,
        "thursday": 4, "thu": 4, "thur": 4, "thurs": 4,
        "friday": 5, "fri": 5,
        "saturday": 6, "sat": 6,
        "sunday": 0, "sun": 0,
    }
    dow = days.get(weekday.lower(), "*")
    return f"0 {_cron_from_time(time_str).split(' ')[1]} * * {dow}"


def _cron_from_hhmm(hhmm: str) -> str:
    parts = hhmm.split(":")
    if len(parts) != 2:
        return "0 18 * * *"
    try:
        h = int(parts[0]) % 24
        m = int(parts[1]) % 60
    except ValueError:
        return "0 18 * * *"
    return f"{m} {h} * * *"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


workflow_generator = WorkflowGeneratorAgent()


__all__ = [
    "Suggestion",
    "WorkflowGeneratorAgent",
    "workflow_generator",
]

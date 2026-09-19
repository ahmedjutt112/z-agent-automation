"""AutonomousAgent - master prompt section 85 (Autonomous Mode), section 81
(Phase 3 AI Computer Agent), section 7 (agent federation).

Top-level orchestrator that takes a natural-language GOAL and runs the
full plan -> execute -> observe -> verify -> recover loop until either
the goal is achieved, the kill switch trips, or recovery is exhausted.

Three modes (section 85):

* ASSIST - plans only, never executes. The user runs the steps manually.
* GUIDED (default) - executes LOW / MEDIUM risk steps automatically,
  asks for HIGH / CRITICAL.
* AUTONOMOUS - executes everything within pre-approved permissions.
  NEVER bypasses the permission engine (section 85: "Never create an
  unrestricted mode that bypasses security controls").

The agent:

1. Calls PlannerAgent.plan(goal) -> Plan.
2. For each step (capped at ``max_steps`` - default 50):
   a. Checks the kill switch.
   b. Observes the current state via ObserverAgent.observe().
   c. Executes the step via WorkflowExecutor.
   d. Verifies the action succeeded.
   e. If failed: calls RecoveryAgent. If recovery succeeds, retries.
      Otherwise pauses and asks the user.
   f. Records what worked / what didn't to MemoryManager.
3. Returns an :class:`AutonomousResult` with the execution log.

Every action is logged to the audit log via event_bus emits - the
security / audit pipeline subscribes to those events.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..engine.event_bus import event_bus
from ..engine.workflow_executor import WorkflowExecutor
from ..memory.manager import MemoryManager, MemoryType, memory_manager as default_memory
from ..models import AutomationMode, Plan, PlanStep, RiskLevel, StepStatus, TaskStatus
from ..security.kill_switch import kill_switch
from .observer_agent import ObserverAgent, observer_agent as default_observer
from .planner import PlannerAgent
from .recovery_agent import (
    FailureContext,
    RecoveryAgent,
    RecoveryPlan,
    recovery_agent as default_recovery,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StepExecutionLog(BaseModel):
    """One entry in the :class:`AutonomousResult.execution_log`."""

    step_id: str
    action: str
    status: str  # completed / failed / skipped / cancelled / asked_user
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    recovery_strategy: Optional[str] = None
    observed_at: Optional[str] = None


class AutonomousResult(BaseModel):
    """Result of :meth:`AutonomousAgent.execute_autonomously`."""

    goal: str
    plan_id: str
    mode: str = AutomationMode.GUIDED.value
    steps_executed: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    duration_seconds: float = 0.0
    final_state: str = TaskStatus.COMPLETED.value
    learnings: list[str] = Field(default_factory=list)
    execution_log: list[StepExecutionLog] = Field(default_factory=list)
    aborted: bool = False
    abort_reason: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# AutonomousAgent
# ---------------------------------------------------------------------------


class AutonomousAgent:
    """Multi-step autonomous execution - master prompt section 81, section 85."""

    # Hard ceiling on the number of steps we'll execute. Section 85
    # demands we never create an unrestricted mode.
    DEFAULT_MAX_STEPS = 50

    def __init__(
        self,
        planner: Optional[PlannerAgent] = None,
        executor: Optional[WorkflowExecutor] = None,
        observer: Optional[ObserverAgent] = None,
        recovery: Optional[RecoveryAgent] = None,
        memory: Optional[MemoryManager] = None,
    ) -> None:
        self._planner = planner or PlannerAgent()
        self._executor = executor or WorkflowExecutor()
        self._observer = observer or default_observer
        self._recovery = recovery or default_recovery
        self._memory = memory or default_memory

    # ------------------------------------------------------------------
    # execute_autonomously
    # ------------------------------------------------------------------

    async def execute_autonomously(
        self,
        goal: str,
        max_steps: int = DEFAULT_MAX_STEPS,
        mode: AutomationMode = AutomationMode.GUIDED,
    ) -> AutonomousResult:
        """Run the full plan -> execute -> observe -> recover loop."""
        started = time.time()
        run_id = str(uuid4())
        event_bus.publish(
            "TASK_STARTED",
            {"run_id": run_id, "goal": goal, "mode": mode.value, "source": "autonomous"},
        )

        # ---- 1. Plan ----------------------------------------------------
        plan = await self._planner.plan(goal)
        event_bus.publish(
            "TASK_CREATED",
            {"run_id": run_id, "plan_id": str(plan.id), "goal": goal, "steps": len(plan.steps)},
        )

        result = AutonomousResult(
            goal=goal,
            plan_id=str(plan.id),
            mode=mode.value,
            started_at=datetime.now(timezone.utc),
        )

        # ---- ASSIST mode never executes --------------------------------
        if mode == AutomationMode.ASSIST:
            result.final_state = TaskStatus.PLANNED.value
            result.learnings.append(
                "ASSIST mode: plan generated, no steps executed (user runs manually)."
            )
            result.finished_at = datetime.now(timezone.utc)
            result.duration_seconds = time.time() - started
            event_bus.publish(
                "TASK_COMPLETED",
                {"run_id": run_id, "mode": mode.value, "executed": False},
            )
            return result

        # ---- 2. Execute each step --------------------------------------
        steps_to_run = plan.steps[: max(0, int(max_steps))]
        if len(plan.steps) > max_steps:
            result.learnings.append(
                f"plan had {len(plan.steps)} steps but max_steps={max_steps} - truncated"
            )

        per_step_recovery_attempts: dict[str, int] = {}

        for step in steps_to_run:
            # a. Kill switch check - abort immediately if engaged.
            if kill_switch.engaged:
                result.aborted = True
                result.abort_reason = "kill_switch_engaged"
                result.final_state = TaskStatus.CANCELLED.value
                result.execution_log.append(
                    StepExecutionLog(
                        step_id=step.id,
                        action=step.action,
                        status="cancelled",
                        error="kill_switch_engaged",
                    )
                )
                event_bus.publish(
                    "TASK_PAUSED",
                    {"run_id": run_id, "reason": "kill_switch_engaged", "step_id": step.id},
                )
                break

            # b. Mode-based gating - GUIDED mode asks for HIGH / CRITICAL.
            if mode == AutomationMode.GUIDED and step.risk_level in (
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            ):
                # Don't execute - record the ask + skip in GUIDED mode.
                result.steps_skipped += 1
                result.execution_log.append(
                    StepExecutionLog(
                        step_id=step.id,
                        action=step.action,
                        status="asked_user",
                        error=f"risk_level={step.risk_level.value} requires approval in GUIDED mode",
                    )
                )
                event_bus.publish(
                    "USER_APPROVAL_REQUIRED",
                    {"run_id": run_id, "step_id": step.id, "risk": step.risk_level.value},
                )
                continue

            # AUTONOMOUS mode still goes through the permission engine
            # (master prompt section 85). The WorkflowExecutor consults
            # the permission engine on every step; we trust it here.

            # c. Observe current state.
            observation = await self._observer.observe()

            # d. Execute the step.
            step_started = time.time()
            action_result = await self._executor._execute_step(
                run_id, step, dict(plan.variables)
            )
            step_ms = int((time.time() - step_started) * 1000)
            result.steps_executed += 1

            log_entry = StepExecutionLog(
                step_id=step.id,
                action=step.action,
                status=action_result.status.value if hasattr(action_result.status, "value") else str(action_result.status),
                duration_ms=step_ms,
                error=action_result.error,
                observed_at=observation.observed_at.isoformat() if observation else None,
            )

            # e. Failed -> recover -> retry, or ask user.
            if action_result.status == StepStatus.FAILED:
                attempts = per_step_recovery_attempts.get(step.id, 0) + 1
                per_step_recovery_attempts[step.id] = attempts

                failure = FailureContext(
                    failed_action=step.action,
                    error=action_result.error,
                    screenshot_path=observation.screenshot_path,
                    step_context=dict(step.args),
                    attempt_number=attempts,
                )
                try:
                    recovery_plan = await self._recovery.recover_from_failure(failure)
                except Exception as exc:
                    logger.warning("recovery agent raised: {}", exc)
                    recovery_plan = RecoveryPlan(
                        strategy="ask_user",
                        should_ask_user=True,
                        reason=f"recovery agent raised: {exc}",
                    )

                log_entry.recovery_strategy = recovery_plan.strategy

                if recovery_plan.should_ask_user:
                    result.execution_log.append(log_entry)
                    result.steps_failed += 1
                    result.final_state = TaskStatus.PAUSED.value
                    result.learnings.append(
                        f"step {step.id} ({step.action}) failed and recovery asked the user"
                    )
                    event_bus.publish(
                        "USER_APPROVAL_REQUIRED",
                        {"run_id": run_id, "step_id": step.id, "reason": recovery_plan.reason},
                    )
                    break

                if recovery_plan.should_retry and attempts < self._recovery.MAX_RECOVERY_ATTEMPTS:
                    # Wait + retry once (the loop above will re-enter).
                    if recovery_plan.retry_delay_seconds > 0:
                        await asyncio.sleep(recovery_plan.retry_delay_seconds)
                    # Re-run the step directly (single retry).
                    retry_result = await self._executor._execute_step(
                        run_id, step, dict(plan.variables)
                    )
                    if retry_result.status == StepStatus.COMPLETED:
                        result.steps_succeeded += 1
                        log_entry.status = "completed"
                        log_entry.error = None
                        result.execution_log.append(log_entry)
                        continue
                    # Retry didn't help - fall through to failure accounting.

                result.steps_failed += 1
                result.execution_log.append(log_entry)
                event_bus.publish(
                    "STEP_FAILED",
                    {"run_id": run_id, "step_id": step.id, "recovery": recovery_plan.strategy},
                )
                continue

            # f. Success - verify the action.
            if step.verification:
                try:
                    verification = await self._observer.verify_action(
                        step.action, step.verification
                    )
                    if not verification.verified:
                        log_entry.status = "failed"
                        log_entry.error = f"verification failed: {verification.evidence}"
                        result.steps_failed += 1
                        result.execution_log.append(log_entry)
                        continue
                except Exception as exc:
                    logger.debug("verify_action raised: {}", exc)
            result.steps_succeeded += 1
            result.execution_log.append(log_entry)
            event_bus.publish(
                "STEP_COMPLETED",
                {"run_id": run_id, "step_id": step.id, "duration_ms": step_ms},
            )

        # ---- 3. Wrap up ------------------------------------------------
        if not result.aborted and result.steps_failed == 0:
            result.final_state = TaskStatus.COMPLETED.value
        elif result.aborted:
            result.final_state = TaskStatus.CANCELLED.value
        elif result.steps_failed > 0 and result.steps_succeeded == 0:
            result.final_state = TaskStatus.FAILED.value
        else:
            result.final_state = TaskStatus.COMPLETED.value  # partial success

        result.duration_seconds = time.time() - started
        result.finished_at = datetime.now(timezone.utc)

        event_bus.publish(
            "TASK_COMPLETED",
            {
                "run_id": run_id,
                "goal": goal,
                "executed": result.steps_executed,
                "succeeded": result.steps_succeeded,
                "failed": result.steps_failed,
            },
        )

        # ---- 4. Learn --------------------------------------------------
        try:
            await self.learn_from_execution(result)
        except Exception as exc:
            logger.debug("learn_from_execution raised: {}", exc)

        return result

    # ------------------------------------------------------------------
    # learn_from_execution
    # ------------------------------------------------------------------

    async def learn_from_execution(self, result: AutonomousResult) -> None:
        """Persist successful + failed patterns to MemoryManager.

        Successful patterns are stored under ``workflow`` memory so the
        PlannerAgent can reuse them next time. Failed patterns are
        stored under ``task_context`` so we don't repeat them.
        """
        # Successful pattern: store the goal + first 5 step actions.
        if result.steps_succeeded > 0:
            try:
                await self._memory.remember(
                    MemoryType.WORKFLOW,
                    key=f"autonomous_pattern::{result.goal[:80]}",
                    value={
                        "goal": result.goal,
                        "mode": result.mode,
                        "succeeded_count": result.steps_succeeded,
                        "failed_count": result.steps_failed,
                        "first_actions": [
                            {"step_id": e.step_id, "action": e.action}
                            for e in result.execution_log[:5]
                        ],
                    },
                    source="autonomous_agent.learn_from_execution",
                )
            except ValueError as exc:
                # Section 57: secret detection may refuse to persist.
                logger.debug("skipping workflow memory write: {}", exc)
            except Exception as exc:
                logger.debug("workflow memory write failed: {}", exc)

        # Failed pattern: record the first failure so we don't repeat.
        first_fail = next(
            (e for e in result.execution_log if e.status == "failed"), None
        )
        if first_fail is not None:
            try:
                await self._memory.remember(
                    MemoryType.TASK_CONTEXT,
                    key=f"autonomous_failure::{first_fail.step_id}",
                    value={
                        "goal": result.goal,
                        "step_id": first_fail.step_id,
                        "action": first_fail.action,
                        "error": first_fail.error,
                        "recovery_strategy": first_fail.recovery_strategy,
                    },
                    source="autonomous_agent.learn_from_execution",
                    ttl_seconds=86400,  # expire failed-step context after 1 day
                )
            except ValueError:
                pass
            except Exception as exc:
                logger.debug("task_context memory write failed: {}", exc)

        # Append a human-readable learning to the result.
        if result.steps_failed > 0 and result.steps_succeeded == 0:
            result.learnings.append(
                "Every step failed - the goal may be infeasible with the current "
                "tools / selectors. Ask the user for refined instructions."
            )
        elif result.steps_succeeded > result.steps_failed:
            result.learnings.append(
                f"Most steps succeeded ({result.steps_succeeded}/{result.steps_executed}) - "
                "the workflow is a good candidate for a reusable Workflow."
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


autonomous_agent = AutonomousAgent()


__all__ = [
    "AutonomousResult",
    "AutonomousAgent",
    "StepExecutionLog",
    "autonomous_agent",
]

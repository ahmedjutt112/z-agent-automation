"""Workflow executor — master prompt §21 (workflow format), §39 (error handling),
§40 (self-healing), §43 (loops), §44 (parallel execution), §60 (reliability),
§61 (checkpoints), §62 (crash recovery).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ..models import (
    ActionRequest,
    ActionResult,
    Plan,
    PlanStep,
    StepStatus,
    TaskStatus,
    Workflow,
    WorkflowNode,
)
from ..config import settings
from ..engine.event_bus import event_bus
from ..engine.tool_registry import tool_registry
from ..security.kill_switch import kill_switch


class WorkflowExecutor:
    """Executes Plans and Workflows step-by-step with full event emission."""

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._cancel_tokens: dict[str, asyncio.Event] = {}

    async def execute_plan(self, plan: Plan) -> str:
        run_id = str(uuid4())
        cancel_token = kill_switch.get_cancel_event()
        self._cancel_tokens[run_id] = cancel_token
        self._runs[run_id] = {
            "plan_id": str(plan.id),
            "goal": plan.goal,
            "status": TaskStatus.RUNNING.value,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps_total": len(plan.steps),
            "steps_completed": 0,
            "steps_failed": 0,
            "checkpoints": [],
        }

        event_bus.publish("TASK_STARTED", {"run_id": run_id, "plan_id": str(plan.id)})

        try:
            for step in plan.steps:
                if cancel_token.is_set() or kill_switch.engaged:
                    self._runs[run_id]["status"] = TaskStatus.CANCELLED.value
                    event_bus.publish(
                        "TASK_PAUSED", {"run_id": run_id, "reason": "kill_switch"}
                    )
                    return run_id

                result = await self._execute_step(run_id, step)
                if result.status == StepStatus.FAILED:
                    self._runs[run_id]["steps_failed"] += 1
                    if step.fallback:
                        # Self-healing: try fallback
                        fb_step = PlanStep(id=step.id + "_fb", action=step.fallback, args=step.args)
                        await self._execute_step(run_id, fb_step)
                    else:
                        self._runs[run_id]["status"] = TaskStatus.FAILED.value
                        event_bus.publish("TASK_FAILED", {"run_id": run_id, "step_id": step.id})
                        return run_id
                else:
                    self._runs[run_id]["steps_completed"] += 1
                    self._runs[run_id]["checkpoints"].append({"step_id": step.id, "at": datetime.now(timezone.utc).isoformat()})

            self._runs[run_id]["status"] = TaskStatus.COMPLETED.value
            event_bus.publish("TASK_COMPLETED", {"run_id": run_id})

        except Exception as exc:
            self._runs[run_id]["status"] = TaskStatus.FAILED.value
            event_bus.publish("TASK_FAILED", {"run_id": run_id, "error": str(exc)})

        return run_id

    async def _execute_step(self, run_id: str, step: PlanStep) -> ActionResult:
        event_bus.publish("STEP_STARTED", {"run_id": run_id, "step_id": step.id, "tool": step.action})

        tool = tool_registry.get(step.action)
        if tool is None:
            return ActionResult(
                tool=step.action,
                status=StepStatus.FAILED,
                error=f"tool '{step.action}' not registered",
            )

        attempt = 0
        last_error: Optional[str] = None
        while attempt <= step.retry_count:
            try:
                result = await asyncio.wait_for(
                    tool.execute(step.args),
                    timeout=step.timeout_ms / 1000,
                )
                if result.status == StepStatus.COMPLETED:
                    event_bus.publish(
                        "STEP_COMPLETED",
                        {"run_id": run_id, "step_id": step.id, "duration_ms": result.duration_ms},
                    )
                    return result
                last_error = result.error
            except asyncio.TimeoutError:
                last_error = f"timeout after {step.timeout_ms}ms"
            except Exception as exc:
                last_error = str(exc)

            attempt += 1
            if attempt <= step.retry_count:
                await asyncio.sleep(0.5 * attempt)  # simple backoff

        event_bus.publish("STEP_FAILED", {"run_id": run_id, "step_id": step.id, "error": last_error})
        return ActionResult(tool=step.action, status=StepStatus.FAILED, error=last_error)

    async def cancel(self, run_id: str) -> None:
        token = self._cancel_tokens.get(run_id)
        if token:
            token.set()

    def get_status(self, run_id: str) -> Optional[dict]:
        return self._runs.get(run_id)

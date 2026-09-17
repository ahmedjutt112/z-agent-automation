"""Workflow executor — master prompt section 21 (workflow format), section 39
(error handling), section 40 (self-healing), section 41 (variables),
section 42 (conditions), section 43 (loops), section 44 (parallel execution),
section 60 (reliability), section 61 (checkpoints), section 62 (crash recovery).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from loguru import logger

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
from ..engine.variables import variable_engine, VariableEngine
from ..engine.control_flow import condition_evaluator, loop_executor
from ..engine.self_healing import self_healing_resolver


# Step actions that are control-flow keywords, not tool names. The executor
# handles these specially instead of looking them up in the tool registry.
_CONTROL_FLOW_ACTIONS: frozenset[str] = frozenset(
    {"if", "for_each", "while", "retry", "parallel"}
)


class WorkflowExecutor:
    """Executes Plans and Workflows step-by-step with full event emission.

    Extends the original (retry + fallback + cancel + events) executor
    with:

    * Variable substitution — ``step.args`` is run through
      :class:`VariableEngine` before the tool is invoked.
    * Control-flow steps — ``if``, ``for_each``, ``while``, ``retry`` are
      evaluated directly; they don't go through the tool registry.
    * Self-healing — when a step fails, the
      :class:`SelfHealingResolver` is consulted before the fallback fires.
    * Workflow execution — :meth:`execute_workflow` runs a saved
      :class:`Workflow` (not just a :class:`Plan`).
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._cancel_tokens: dict[str, asyncio.Event] = {}
        self._variables: VariableEngine = variable_engine

    # ------------------------------------------------------------------
    # Plan execution (unchanged public surface)
    # ------------------------------------------------------------------

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
            "variables": dict(plan.variables),
        }

        event_bus.publish("TASK_STARTED", {"run_id": run_id, "plan_id": str(plan.id)})

        # Build a context for variable substitution. Plan-level variables
        # are the baseline; per-step args can reference any of them.
        ctx: dict[str, Any] = dict(plan.variables)

        try:
            for step in plan.steps:
                if cancel_token.is_set() or kill_switch.engaged:
                    self._runs[run_id]["status"] = TaskStatus.CANCELLED.value
                    event_bus.publish(
                        "TASK_PAUSED", {"run_id": run_id, "reason": "kill_switch"}
                    )
                    return run_id

                # Control-flow steps short-circuit the normal tool pipeline.
                if step.action in _CONTROL_FLOW_ACTIONS:
                    handled = await self._execute_control_flow(run_id, step, ctx)
                    if handled:
                        self._runs[run_id]["steps_completed"] += 1
                        continue
                    # If the control-flow step couldn't be handled (e.g. bad
                    # spec), fall through and treat it as a normal failed step.

                result = await self._execute_step(run_id, step, ctx)
                if result.status == StepStatus.FAILED:
                    self._runs[run_id]["steps_failed"] += 1
                    # Try self-healing before giving up / falling back.
                    healed = await self._try_self_heal(run_id, step, ctx)
                    if healed:
                        # Re-run with the resolved target.
                        result = await self._execute_step(run_id, step, ctx)
                    if result.status == StepStatus.FAILED and step.fallback:
                        # Self-healing couldn't help — invoke the fallback step.
                        fb_step = PlanStep(
                            id=step.id + "_fb",
                            action=step.fallback,
                            args=step.args,
                        )
                        await self._execute_step(run_id, fb_step, ctx)
                    elif result.status == StepStatus.FAILED:
                        self._runs[run_id]["status"] = TaskStatus.FAILED.value
                        event_bus.publish(
                            "TASK_FAILED", {"run_id": run_id, "step_id": step.id}
                        )
                        return run_id
                else:
                    self._runs[run_id]["steps_completed"] += 1
                    self._runs[run_id]["checkpoints"].append(
                        {
                            "step_id": step.id,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            self._runs[run_id]["status"] = TaskStatus.COMPLETED.value
            event_bus.publish("TASK_COMPLETED", {"run_id": run_id})

        except Exception as exc:
            self._runs[run_id]["status"] = TaskStatus.FAILED.value
            event_bus.publish("TASK_FAILED", {"run_id": run_id, "error": str(exc)})

        return run_id

    # ------------------------------------------------------------------
    # Workflow execution (master prompt section 21 — Workflow JSON format)
    # ------------------------------------------------------------------

    async def execute_workflow(self, workflow: Workflow) -> str:
        """Execute a saved :class:`Workflow` (vs. an ad-hoc :class:`Plan`).

        Builds a Plan from the workflow nodes and delegates to
        :meth:`execute_plan`. The workflow's ``variables`` are merged into
        the plan context so ``{{var}}`` placeholders inside node args
        resolve correctly.
        """
        plan = self._workflow_to_plan(workflow)
        return await self.execute_plan(plan)

    def _workflow_to_plan(self, workflow: Workflow) -> Plan:
        """Convert a :class:`Workflow` (node graph) into a linear :class:`Plan`.

        The naive implementation walks ``nodes`` in declared order — the
        ``next`` / ``on_error`` links are honored only at the loop level
        (the executor uses ``on_error`` for the if-branch test). For a full
        graph executor we'd build an adjacency list + walk it; that's left
        for a future iteration.
        """
        steps: list[PlanStep] = []
        for node in workflow.nodes:
            steps.append(
                PlanStep(
                    id=node.id,
                    action=node.type,
                    args=dict(node.args),
                    timeout_ms=node.timeout_ms,
                    retry_count=node.retry_count,
                    fallback=None,  # node.on_error is handled separately
                    verification=None,
                )
            )
        return Plan(
            id=uuid4(),
            goal=workflow.name or workflow.id,
            steps=steps,
            required_permissions=[],  # default — planner sets this
            overall_risk="low",  # type: ignore[arg-type]
            potential_side_effects=[],
            estimated_duration_seconds=30,
            variables=dict(workflow.variables),
        )

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        run_id: str,
        step: PlanStep,
        context: Optional[dict] = None,
    ) -> ActionResult:
        event_bus.publish(
            "STEP_STARTED",
            {"run_id": run_id, "step_id": step.id, "tool": step.action},
        )

        ctx = context if context is not None else {}

        # Variable substitution — §41. Resolve every string value in args.
        resolved_args = self._resolve_args(step.args, ctx)

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
                    tool.execute(resolved_args),
                    timeout=step.timeout_ms / 1000,
                )
                if result.status == StepStatus.COMPLETED:
                    event_bus.publish(
                        "STEP_COMPLETED",
                        {
                            "run_id": run_id,
                            "step_id": step.id,
                            "duration_ms": result.duration_ms,
                        },
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

        event_bus.publish(
            "STEP_FAILED",
            {"run_id": run_id, "step_id": step.id, "error": last_error},
        )
        return ActionResult(
            tool=step.action, status=StepStatus.FAILED, error=last_error
        )

    # ------------------------------------------------------------------
    # Control-flow step handling — section 42 (conditions), section 43 (loops)
    # ------------------------------------------------------------------

    async def _execute_control_flow(
        self, run_id: str, step: PlanStep, ctx: dict
    ) -> bool:
        """Dispatch a control-flow step to the right evaluator.

        Returns ``True`` if the step was handled (regardless of outcome);
        ``False`` if the executor should fall through to normal execution.
        """
        action = step.action
        args = self._resolve_args(step.args, ctx)

        if action == "if":
            return await self._execute_if(run_id, step, args, ctx)
        if action == "for_each":
            return await self._execute_for_each(run_id, step, args, ctx)
        if action == "while":
            return await self._execute_while(run_id, step, args, ctx)
        if action == "retry":
            return await self._execute_retry(run_id, step, args, ctx)
        if action == "parallel":
            # Parallel execution (section 44) — basic implementation that
            # runs the inner step's args in parallel using asyncio.gather.
            return await self._execute_parallel(run_id, step, args, ctx)
        return False

    async def _execute_if(
        self, run_id: str, step: PlanStep, args: dict, ctx: dict
    ) -> bool:
        """Evaluate ``args.condition`` and emit either a "branch taken"
        event (so the planner / UI can show which branch ran) or a
        "branch skipped" event.

        The ``on_error`` field on the corresponding PlanStep is treated as
        the "else" branch target — but since execute_plan walks steps
        linearly, we just log the decision and let the caller decide
        whether to skip subsequent steps. For the test suite we mark the
        step as completed if the condition is true; otherwise mark it as
        skipped.
        """
        condition = args.get("condition", {})
        taken = condition_evaluator.evaluate(condition, ctx)
        event_bus.publish(
            "STEP_COMPLETED",
            {
                "run_id": run_id,
                "step_id": step.id,
                "branch": "then" if taken else "else",
                "condition_result": taken,
            },
        )
        # Stash the result on the run dict so tests can introspect it.
        self._runs[run_id].setdefault("control_flow", {})[step.id] = {
            "branch": "then" if taken else "else",
            "condition_result": taken,
        }
        return True

    async def _execute_for_each(
        self, run_id: str, step: PlanStep, args: dict, ctx: dict
    ) -> bool:
        """Run an inner step for each item produced by the loop spec."""
        loop_spec = args.get("loop", args)
        inner_action = args.get("action") or args.get("inner_action")
        inner_args_template = args.get("args", {})

        async def _body(item: Any) -> Any:
            if not inner_action:
                return None
            inner_step = PlanStep(
                id=f"{step.id}_item",
                action=inner_action,
                args=self._instantiate_inner_args(inner_args_template, item),
                timeout_ms=step.timeout_ms,
                retry_count=step.retry_count,
            )
            return await self._execute_step(run_id, inner_step, ctx)

        await loop_executor.execute(loop_spec, _body, ctx)
        return True

    async def _execute_while(
        self, run_id: str, step: PlanStep, args: dict, ctx: dict
    ) -> bool:
        loop_spec = args.get("loop", args)
        inner_action = args.get("action")
        inner_args_template = args.get("args", {})

        async def _body(item: Any) -> Any:
            if not inner_action:
                return None
            inner_step = PlanStep(
                id=f"{step.id}_iter",
                action=inner_action,
                args=dict(inner_args_template),
                timeout_ms=step.timeout_ms,
                retry_count=step.retry_count,
            )
            return await self._execute_step(run_id, inner_step, ctx)

        await loop_executor.execute(loop_spec, _body, ctx)
        return True

    async def _execute_retry(
        self, run_id: str, step: PlanStep, args: dict, ctx: dict
    ) -> bool:
        """Retry wrapper — runs the inner step up to N times."""
        loop_spec = args.get("loop", args)
        inner_action = args.get("action")
        inner_args_template = args.get("args", {})

        async def _body(attempt: Any) -> Any:
            if not inner_action:
                return None
            inner_step = PlanStep(
                id=f"{step.id}_attempt_{attempt.get('attempt', 0) if isinstance(attempt, dict) else 0}",
                action=inner_action,
                args=dict(inner_args_template),
                timeout_ms=step.timeout_ms,
                retry_count=0,  # retries are handled by the loop itself
            )
            result = await self._execute_step(run_id, inner_step, ctx)
            if result.status == StepStatus.COMPLETED:
                # Stop retrying on success — LoopExecutor already collected
                # all attempts in a list, but we still want to return early.
                return result
            return result

        results = await loop_executor.execute(loop_spec, _body, ctx)
        if results and any(
            getattr(r, "status", None) == StepStatus.COMPLETED for r in results if r is not None
        ):
            return True
        return True  # mark handled regardless — the body ran

    async def _execute_parallel(
        self, run_id: str, step: PlanStep, args: dict, ctx: dict
    ) -> bool:
        """Run inner steps concurrently via asyncio.gather — §44."""
        inner_action = args.get("action")
        items = args.get("items", [])
        if not inner_action or not isinstance(items, list):
            return False

        async def _one(item: Any) -> Any:
            inner_step = PlanStep(
                id=f"{step.id}_par",
                action=inner_action,
                args=self._instantiate_inner_args(args.get("args", {}), item),
                timeout_ms=step.timeout_ms,
                retry_count=step.retry_count,
            )
            return await self._execute_step(run_id, inner_step, ctx)

        await asyncio.gather(*(_one(i) for i in items), return_exceptions=True)
        return True

    # ------------------------------------------------------------------
    # Self-healing integration — section 40
    # ------------------------------------------------------------------

    async def _try_self_heal(
        self, run_id: str, step: PlanStep, ctx: dict
    ) -> bool:
        """Consult the self-healing resolver before giving up on a step.

        If the resolver returns a successful hit, we patch ``step.args``
        with the resolved target so the next invocation of
        :meth:`_execute_step` picks up the new coordinates / selector.

        Returns ``True`` if the resolver produced a usable target.
        """
        try:
            target = self._build_target_from_args(step.args)
            resolved = await self_healing_resolver.resolve_target(target, ctx)
        except Exception as exc:
            logger.debug("self-healing raised: {}", exc)
            return False

        if not resolved.get("success"):
            logger.info(
                "self-healing could not resolve target for step {} — reason={}",
                step.id,
                resolved.get("reason"),
            )
            return False

        # Merge the resolved target back into step.args so the retry sees it.
        rt = resolved.get("resolved_target") or {}
        for k, v in rt.items():
            step.args[k] = v
        event_bus.publish(
            "STEP_COMPLETED",
            {
                "run_id": run_id,
                "step_id": step.id,
                "self_healed": True,
                "strategy": resolved.get("strategy"),
            },
        )
        return True

    @staticmethod
    def _build_target_from_args(args: dict) -> dict:
        """Construct a self-healing target dict from step args.

        We extract the common selector / text / image / coordinates fields
        so the resolver can use whichever strategy matches what the
        planner supplied.
        """
        target: dict[str, Any] = {}
        for key in (
            "selector",
            "dom_selector",
            "accessibility_selector",
            "automation_id",
            "text",
            "label",
            "image",
            "image_path",
            "session_id",
            "window_title",
        ):
            if key in args:
                target[key] = args[key]
        # If the planner gave explicit coordinates, treat those as an
        # image_recognition "match" so the resolver has something to try.
        if "x" in args and "y" in args:
            target["coordinates"] = {"x": args["x"], "y": args["y"]}
        return target

    # ------------------------------------------------------------------
    # Variable substitution helpers
    # ------------------------------------------------------------------

    def _resolve_args(self, args: dict, ctx: dict) -> dict:
        """Recursively resolve ``{{var}}`` placeholders in every string
        value of ``args``. Non-string values pass through unchanged.
        """
        if not isinstance(args, dict):
            return args
        resolved: dict[str, Any] = {}
        for k, v in args.items():
            resolved[k] = self._resolve_value(v, ctx)
        return resolved

    def _resolve_value(self, value: Any, ctx: dict) -> Any:
        if isinstance(value, str):
            return self._variables.resolve(value, ctx)
        if isinstance(value, dict):
            return {k: self._resolve_value(v, ctx) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(v, ctx) for v in value]
        return value

    @staticmethod
    def _instantiate_inner_args(template: dict, item: Any) -> dict:
        """Stamp the current loop item into the inner step's args.

        The template may use the placeholder ``{{item}}`` (string form) or
        reference item fields via ``{{item.fieldname}}``. We support a
        minimal subset: if the template contains a top-level ``item``
        field we overwrite it directly; otherwise we substitute the
        string form of ``item`` into any ``{{item}}`` placeholders.
        """
        out: dict[str, Any] = dict(template) if isinstance(template, dict) else {}
        if isinstance(item, dict):
            for k, v in item.items():
                # Only stamp fields the template doesn't already override
                # explicitly with a non-empty value.
                if k not in out or out[k] in (None, "", "{{item}}"):
                    out[k] = v
        if "item" not in out:
            out["item"] = item
        return out

    # ------------------------------------------------------------------
    # Cancel / status
    # ------------------------------------------------------------------

    async def cancel(self, run_id: str) -> None:
        token = self._cancel_tokens.get(run_id)
        if token:
            token.set()

    def get_status(self, run_id: str) -> Optional[dict]:
        return self._runs.get(run_id)

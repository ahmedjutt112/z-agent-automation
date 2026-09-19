"""FastAPI router for the Phase 3 AI Computer Agent - master prompt section 81.

Mounted under ``/agent`` in main.py. All routes require the IPC bearer
token (resolved lazily from ``automation_service.main`` to avoid a
circular import).

Endpoints
---------

Observation / vision:
* ``POST /agent/observe``                - take a screenshot + analyse it.
* ``POST /agent/find-element``           - body: {description} -> TargetLocation.
* ``POST /agent/verify-action``          - body: {action, expected_result}.
* ``POST /agent/analyze-screenshot``     - body: {image_path, question?}.
* ``POST /agent/compare-screenshots``   - body: {before, after}.

Recovery + autonomous execution:
* ``POST /agent/recover``               - body: {failure_context} -> RecoveryPlan.
* ``POST /agent/execute-autonomously``  - body: {goal, max_steps?, mode?}.

Workflow generation:
* ``POST /agent/generate-workflow``     - body: {description}.
* ``POST /agent/improve-workflow``       - body: {workflow_id, feedback}.
* ``GET  /agent/suggestions``            - list automation suggestions.

CRITICAL: every autonomous-execution route still routes actions through
the WorkflowExecutor + permission engine (master prompt section 85 - never
create an unrestricted mode that bypasses security controls).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..agents.autonomous_agent import AutonomousAgent, autonomous_agent
from ..agents.observer_agent import ObserverAgent, observer_agent
from ..agents.recovery_agent import FailureContext, RecoveryAgent, recovery_agent
from ..agents.vision_agent import VisionAgent, vision_agent
from ..agents.workflow_generator import (
    Suggestion,
    WorkflowGeneratorAgent,
    workflow_generator,
)
from ..config import settings
from ..models import AutomationMode, Workflow


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency - lazy import avoids circular dep with main.
# ---------------------------------------------------------------------------


async def _verify_ipc_token(authorization: str | None = None) -> None:
    from ..main import verify_ipc_token

    await verify_ipc_token(authorization)


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------


class ObserveRequest(BaseModel):
    screenshot_path: Optional[str] = Field(
        None,
        description="Optional existing screenshot path. If omitted, the agent "
        "captures a fresh one.",
    )


class FindElementRequest(BaseModel):
    description: str = Field(..., description="Target description or selector.")
    screenshot_path: Optional[str] = None
    browser_session_id: Optional[str] = None


class VerifyActionRequest(BaseModel):
    action: str
    expected_result: str


class RecoverRequest(BaseModel):
    failed_action: str
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    step_context: dict[str, Any] = Field(default_factory=dict)
    attempt_number: int = 0


class ExecuteAutonomouslyRequest(BaseModel):
    goal: str
    max_steps: int = Field(50, ge=1, le=200)
    mode: AutomationMode = AutomationMode.GUIDED


class GenerateWorkflowRequest(BaseModel):
    description: str


class ImproveWorkflowRequest(BaseModel):
    workflow_id: str = Field(..., description="The workflow to improve.")
    feedback: str = Field(..., description="NL feedback on what to change.")


class AnalyzeScreenshotRequest(BaseModel):
    image_path: str
    question: str = ""


class CompareScreenshotsRequest(BaseModel):
    before: str
    after: str


# ---------------------------------------------------------------------------
# Routes - observation / vision
# ---------------------------------------------------------------------------


@router.post(
    "/observe",
    dependencies=[Depends(_verify_ipc_token)],
)
async def observe(req: ObserveRequest) -> dict:
    """Take a screenshot + run OCR + vision analysis."""
    observation = await observer_agent.observe(req.screenshot_path)
    return observation.model_dump(mode="json")


@router.post(
    "/find-element",
    dependencies=[Depends(_verify_ipc_token)],
)
async def find_element(req: FindElementRequest) -> dict:
    """Find a UI element via the section 13 cascade."""
    loc = await observer_agent.find_element(
        req.description,
        screenshot_path=req.screenshot_path,
        browser_session_id=req.browser_session_id,
    )
    if loc is None:
        return {"found": False, "reason": "ask_user", "description": req.description}
    return {"found": True, "location": loc.model_dump(mode="json")}


@router.post(
    "/verify-action",
    dependencies=[Depends(_verify_ipc_token)],
)
async def verify_action(req: VerifyActionRequest) -> dict:
    """Verify an action's expected result."""
    result = await observer_agent.verify_action(req.action, req.expected_result)
    return result.model_dump(mode="json")


@router.post(
    "/analyze-screenshot",
    dependencies=[Depends(_verify_ipc_token)],
)
async def analyze_screenshot(req: AnalyzeScreenshotRequest) -> dict:
    """Run vision analysis on a screenshot."""
    analysis = await vision_agent.analyze_screenshot(req.image_path, req.question)
    return analysis.model_dump(mode="json")


@router.post(
    "/compare-screenshots",
    dependencies=[Depends(_verify_ipc_token)],
)
async def compare_screenshots(req: CompareScreenshotsRequest) -> dict:
    """Compare two screenshots and return what changed."""
    diff = await vision_agent.compare_screenshots(req.before, req.after)
    return diff.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Routes - recovery + autonomous execution
# ---------------------------------------------------------------------------


@router.post(
    "/recover",
    dependencies=[Depends(_verify_ipc_token)],
)
async def recover(req: RecoverRequest) -> dict:
    """Analyse a failure + return a :class:`RecoveryPlan`."""
    failure = FailureContext(
        failed_action=req.failed_action,
        error=req.error,
        screenshot_path=req.screenshot_path,
        step_context=req.step_context,
        attempt_number=req.attempt_number,
    )
    plan = await recovery_agent.recover_from_failure(failure)
    return plan.model_dump(mode="json")


@router.post(
    "/execute-autonomously",
    dependencies=[Depends(_verify_ipc_token)],
)
async def execute_autonomously(req: ExecuteAutonomouslyRequest) -> dict:
    """Run the full plan -> execute -> observe -> recover loop.

    Master prompt section 85 - AUTONOMOUS mode still goes through the
    permission engine on every step (never bypasses security controls).
    """
    result = await autonomous_agent.execute_autonomously(
        goal=req.goal,
        max_steps=req.max_steps,
        mode=req.mode,
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Routes - workflow generation
# ---------------------------------------------------------------------------


@router.post(
    "/generate-workflow",
    dependencies=[Depends(_verify_ipc_token)],
)
async def generate_workflow(req: GenerateWorkflowRequest) -> dict:
    """Generate a Workflow from a NL description."""
    wf = await workflow_generator.generate_from_description(req.description)
    return {"workflow": wf.model_dump(mode="json"), "executed": False}


@router.post(
    "/improve-workflow",
    dependencies=[Depends(_verify_ipc_token)],
)
async def improve_workflow(req: ImproveWorkflowRequest) -> dict:
    """Improve a saved workflow based on NL feedback.

    Loads the workflow from ``workflows_dir`` (the same place the
    ``/workflow`` routes read from), applies the feedback, and returns
    the bumped-version Workflow. Does NOT save it - the caller must
    POST it to ``/workflow`` to persist.
    """
    p = settings.workflows_dir / f"{req.workflow_id}.json"
    if not p.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workflow '{req.workflow_id}' not found",
        )
    try:
        wf = Workflow.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"workflow file invalid: {exc}",
        )
    new_wf = await workflow_generator.improve_workflow(wf, req.feedback)
    return {"workflow": new_wf.model_dump(mode="json"), "saved": False}


@router.get(
    "/suggestions",
    dependencies=[Depends(_verify_ipc_token)],
)
async def suggestions() -> list[dict]:
    """Return a list of automation suggestions."""
    sugg = await workflow_generator.suggest_automations()
    return [s.model_dump(mode="json") for s in sugg]


__all__ = ["router"]

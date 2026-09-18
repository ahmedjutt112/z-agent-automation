"""Domain models / enums shared across the automation service.

These are Pydantic v2 models — used for API validation, tool schemas, and
workflow schema. SQLAlchemy ORM models live in ``database/models/``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Master prompt §9 — every action must have a risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionLevel(str, Enum):
    """What level of permission an action requires."""

    NONE = "none"           # No approval needed (read-only, screenshot)
    ALLOW_ONCE = "allow_once"
    ALLOW_FOR_WORKFLOW = "allow_for_workflow"
    ALWAYS_ALLOW = "always_allow"
    DENY = "deny"
    CANCEL = "cancel"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TriggerType(str, Enum):
    """Master prompt §25."""

    SCHEDULE = "schedule"
    FILE = "file"
    APPLICATION = "application"
    BROWSER = "browser"
    HOTKEY = "hotkey"
    WEBHOOK = "webhook"
    SYSTEM = "system"
    MANUAL = "manual"


class AgentRole(str, Enum):
    """Master prompt §7."""

    PLANNER = "planner"
    EXECUTOR = "executor"
    OBSERVER = "observer"
    VERIFICATION = "verification"
    RECOVERY = "recovery"


class AutomationMode(str, Enum):
    """Master prompt §85."""

    ASSIST = "assist"
    GUIDED = "guided"
    AUTONOMOUS = "autonomous"


# ---------------------------------------------------------------------------
# Tool / Action schemas
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """Master prompt §8 — every tool must define these fields."""

    name: str = Field(..., description="Dotted tool name, e.g. 'mouse.click'")
    description: str
    input_schema: dict[str, Any] = Field(..., description="JSON Schema for tool input")
    permission_level: PermissionLevel
    risk_level: RiskLevel
    timeout_ms: int = Field(default=10_000, ge=100, le=600_000)
    rollback_strategy: Optional[str] = None
    verification_strategy: Optional[str] = None


class ActionRequest(BaseModel):
    """A single action requested by the AI planner."""

    tool: str = Field(..., description="Tool name from the registry")
    args: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


class ActionResult(BaseModel):
    """Result of executing an ActionRequest."""

    tool: str
    status: StepStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# Plan / Approval
# ---------------------------------------------------------------------------


class PlanStep(BaseModel):
    """One step in an AI-generated plan."""

    id: str
    action: str = Field(..., description="Tool name, e.g. 'browser.navigate'")
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timeout_ms: int = 10_000
    retry_count: int = 0
    fallback: Optional[str] = None
    verification: Optional[str] = None


class Plan(BaseModel):
    """Master prompt §66 — AI planning safety."""

    id: UUID = Field(default_factory=uuid4)
    goal: str
    steps: list[PlanStep]
    required_permissions: list[PermissionLevel]
    overall_risk: RiskLevel
    potential_side_effects: list[str] = Field(default_factory=list)
    estimated_duration_seconds: int = 30
    variables: dict[str, str] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Master prompt §10 — sent to user when confirmation is required."""

    plan_id: UUID
    step_id: Optional[str]  # If None, asking approval for whole plan
    summary: str
    risk_level: RiskLevel
    destructive_actions: list[str] = Field(default_factory=list)
    options: list[PermissionLevel] = Field(
        default_factory=lambda: [
            PermissionLevel.ALLOW_ONCE,
            PermissionLevel.ALLOW_FOR_WORKFLOW,
            PermissionLevel.ALWAYS_ALLOW,
            PermissionLevel.DENY,
            PermissionLevel.CANCEL,
        ]
    )


class ApprovalResponse(BaseModel):
    plan_id: UUID
    step_id: Optional[str]
    decision: PermissionLevel


# ---------------------------------------------------------------------------
# Workflow schema
# ---------------------------------------------------------------------------


class WorkflowTrigger(BaseModel):
    """Master prompt §21, §24, §25."""

    type: TriggerType
    cron: Optional[str] = None  # for SCHEDULE
    file_pattern: Optional[str] = None  # for FILE
    hotkey: Optional[str] = None  # for HOTKEY
    webhook_url: Optional[str] = None  # for WEBHOOK
    timezone: str = "UTC"


class WorkflowNode(BaseModel):
    """Master prompt §20."""

    id: str
    type: str  # e.g. 'browser.open', 'app.launch', 'if', 'for_each'
    args: dict[str, Any] = Field(default_factory=dict)
    next: Optional[str] = None  # next node id (linear by default)
    on_error: Optional[str] = None  # node id to jump to on error
    timeout_ms: int = 30_000
    retry_count: int = 0
    retry_delay_ms: int = 1000


class Workflow(BaseModel):
    """Master prompt §21 — workflow JSON format."""

    id: str
    name: str
    version: int = 1
    description: Optional[str] = None
    trigger: WorkflowTrigger = Field(default_factory=lambda: WorkflowTrigger(type=TriggerType.MANUAL))
    nodes: list[WorkflowNode]
    variables: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    profile_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

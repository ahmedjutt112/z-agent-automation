"""All ORM models for the 22 tables required by master prompt §27."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# User & profile
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Master prompt §82 — multi-user + team / workspace support.
    team_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("teams.id"), nullable=True, default=None
    )
    default_workspace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class DeviceProfile(Base):
    """Master prompt §49 — multi-profile support."""
    __tablename__ = "device_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_type: Mapped[str] = mapped_column(String(32), default="personal")  # personal/work/dev/test
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# AI Memory — master prompt section 84
# ---------------------------------------------------------------------------


class Memory(Base):
    """Master prompt section 84 — long-term AI memory.

    Five memory types stored in ``memory_type``:
    - ``user_preferences``  (persists forever)
    - ``workflow``          (tied to a workflow_id)
    - ``application``       (per-app behavioral facts)
    - ``task_context``      (tied to a task_id)
    - ``temporary``         (expires after expires_at)

    CRITICAL (section 57): the MemoryManager refuses to remember values that
    look like secrets; the credentials table is the only place secrets live.
    """

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Optional[dict]] = mapped_column(JSON)  # stored as JSON
    source: Mapped[str] = mapped_column(String(64), default="system")
    workflow_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)


# ---------------------------------------------------------------------------
# Settings & AI
# ---------------------------------------------------------------------------


class Setting(Base):
    """Key/value app settings — master prompt §72."""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AIProvider(Base):
    """Master prompt §6 — AI provider config (no secrets stored here)."""
    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)  # openai/anthropic/gemini/ollama/custom
    base_url: Mapped[Optional[str]] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # {vision, reasoning}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    models: Mapped[list["AIModel"]] = relationship(back_populates="provider")


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id"), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255))
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    provider: Mapped[AIProvider] = relationship(back_populates="models")


class APICredential(Base):
    """Master prompt §28 — secrets reference (NOT plain text)."""
    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)  # 'openai', 'anthropic', etc.
    # Store secret in OS credential store; only keep a reference id here.
    credential_store_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Tools & Permissions
# ---------------------------------------------------------------------------


class Tool(Base):
    """Tool registry mirror — master prompt §8."""
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # the tool name (e.g. 'mouse.click')
    description: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    permission_level: Mapped[str] = mapped_column(String(32), default="allow_once")
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    rollback_strategy: Mapped[Optional[str]] = mapped_column(String(255))
    verification_strategy: Mapped[Optional[str]] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Permission(Base):
    """Master prompt §10 — permission grants."""
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # allow_once/always_allow/etc
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class Workflow(Base):
    """Master prompt §21."""
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    latest_version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    versions: Mapped[list["WorkflowVersion"]] = relationship(back_populates="workflow")


class WorkflowVersion(Base):
    """Master prompt §21 — versioned workflows."""
    __tablename__ = "workflow_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_json: Mapped[Optional[dict]] = mapped_column(JSON)
    nodes_json: Mapped[Optional[dict]] = mapped_column(JSON)
    variables_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    workflow: Mapped[Workflow] = relationship(back_populates="versions")


class WorkflowNodeDB(Base):
    """Optional denormalized node records for fast querying."""
    __tablename__ = "workflow_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    args_json: Mapped[Optional[dict]] = mapped_column(JSON)
    next_node: Mapped[Optional[str]] = mapped_column(String(64))
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Runs / Tasks / Steps / Logs
# ---------------------------------------------------------------------------


class WorkflowRun(Base):
    """A single execution of a workflow version."""
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False, index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    mode: Mapped[str] = mapped_column(String(16), default="guided")  # assist/guided/autonomous
    triggered_by: Mapped[str] = mapped_column(String(64), default="manual")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class Task(Base):
    """Master prompt §36."""
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    plan_json: Mapped[Optional[dict]] = mapped_column(JSON)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class TaskStep(Base):
    """Master prompt §36 — task steps with detailed status."""
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args_json: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    output: Mapped[Optional[dict]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class TaskLog(Base):
    """Structured action log — master prompt §37."""
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")  # info/warn/error
    tool: Mapped[Optional[str]] = mapped_column(String(64))
    target: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="info")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)


# ---------------------------------------------------------------------------
# Screenshots & browser sessions
# ---------------------------------------------------------------------------


class Screenshot(Base):
    __tablename__ = "screenshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class BrowserSession(Base):
    """Master prompt §16 — browser session metadata."""
    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    browser_type: Mapped[str] = mapped_column(String(32), default="chromium")
    user_data_dir: Mapped[Optional[str]] = mapped_column(String(512))
    is_persistent: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# Scheduler / Triggers / Notifications
# ---------------------------------------------------------------------------


class ScheduledJob(Base):
    """Master prompt §24."""
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cron: Mapped[Optional[str]] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    retry_policy: Mapped[Optional[dict]] = mapped_column(JSON)
    execution_timeout: Mapped[int] = mapped_column(Integer, default=1800)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Trigger(Base):
    """Master prompt §25 — triggers registry."""
    __tablename__ = "triggers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Notification(Base):
    """Master prompt §26."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), default="desktop")  # desktop/email/webhook/etc
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[Optional[str]] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(16), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


# ---------------------------------------------------------------------------
# History / Audit / Errors
# ---------------------------------------------------------------------------


class AutomationHistory(Base):
    """Master prompt §36 — task history."""
    __tablename__ = "automation_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_profiles.id"), index=True, default=None
    )
    triggered_by: Mapped[str] = mapped_column(String(64), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    actions_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="error")
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), index=True)
    tool: Mapped[Optional[str]] = mapped_column(String(64))
    error_type: Mapped[str] = mapped_column(String(255))
    error_message: Mapped[str] = mapped_column(Text)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text)
    context_json: Mapped[Optional[dict]] = mapped_column(JSON)


class AuditLog(Base):
    """Master prompt §37, §55 — audit trail of every permission decision."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    tool: Mapped[Optional[str]] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(255))
    decision: Mapped[Optional[str]] = mapped_column(String(32))
    risk_level: Mapped[Optional[str]] = mapped_column(String(16))
    request_json: Mapped[Optional[dict]] = mapped_column(JSON)
    response_json: Mapped[Optional[dict]] = mapped_column(JSON)


# Helpful indexes (master prompt §95)
Index("idx_tasks_status_created", Task.status, Task.created_at)
Index("idx_task_logs_task_ts", TaskLog.task_id, TaskLog.timestamp)
Index("idx_audit_logs_ts", AuditLog.timestamp)
Index("idx_workflow_runs_status", WorkflowRun.status)


# ---------------------------------------------------------------------------
# Phase 4 — Professional RPA (master prompt §82)
# Multi-user support, teams, workspaces, RBAC, enterprise policies,
# execution analytics. Existing marketplace / plugins / integrations
# modules from sessions 5-7 already provide the marketplace / plugins /
# integrations mentioned in §82 — these models add the team + policy
# + analytics layer on top.
# ---------------------------------------------------------------------------


class Team(Base):
    """Master prompt §82 — teams for multi-user collaboration."""
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, default=10)
    max_workflows: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class TeamMember(Base):
    """Maps users to teams with roles (owner/admin/member/viewer)."""
    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")  # owner/admin/member/viewer
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/active/revoked
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )


class Workspace(Base):
    """Master prompt §50 — workspace system (team-scoped)."""
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EnterprisePolicy(Base):
    """Master prompt §82 — enterprise policies.

    Policy types:
      - ``max_risk_level``        — block actions above a risk threshold
      - ``allowed_tools``         — only the listed tools may execute
      - ``blocked_tools``         — the listed tools are forbidden
      - ``allowed_domains``       — only these web domains may be navigated to
      - ``require_approval_for``  — actions matching the list need admin approval
      - ``max_daily_runs``        — daily per-team execution cap
      - ``data_residency``        — restrict where data is stored
    """
    __tablename__ = "enterprise_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    policy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_value: Mapped[Optional[dict]] = mapped_column(JSON)
    enforced: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AnalyticsEvent(Base):
    """Master prompt §82 — execution analytics.

    Event types:
      - ``workflow_run``           — a workflow was started
      - ``task_completed``         — a task finished successfully
      - ``task_failed``            — a task failed
      - ``tool_used``              — a tool was invoked
      - ``ai_call``                — an AI provider was called
      - ``permission_granted``     — a permission grant was made
      - ``permission_denied``      — the permission engine denied an action
      - ``login``                  — user login
      - ``export``                 — data export
    """
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[Optional[str]] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_data: Mapped[Optional[dict]] = mapped_column(JSON)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    cost_estimate: Mapped[Optional[float]] = mapped_column(Float)  # for AI calls
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


# Helpful indexes for the new tables (master prompt §95)
Index("idx_team_members_team_id", TeamMember.team_id)
Index("idx_team_members_user_id", TeamMember.user_id)
Index("idx_workspaces_team_id", Workspace.team_id)
Index("idx_enterprise_policies_team_id", EnterprisePolicy.team_id)
Index("idx_analytics_events_team_id", AnalyticsEvent.team_id)
Index("idx_analytics_events_user_id", AnalyticsEvent.user_id)
Index("idx_analytics_events_event_type", AnalyticsEvent.event_type)
Index("idx_analytics_events_created_at", AnalyticsEvent.created_at)

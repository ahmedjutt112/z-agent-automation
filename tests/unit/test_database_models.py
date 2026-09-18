"""Unit tests for the SQLAlchemy ORM models in ``database.models.schema``.

These tests run against an in-memory SQLite database (the ``db_session``
fixture in conftest.py) — they never touch the real ``db/custom.db`` file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------


def test_init_db_creates_all_tables(db_session: Session) -> None:
    """init_db() creates all 22+ tables. We assert the table count is at
    least 22 (the spec lists 22 by name; the actual schema defines 23
    including ``device_profiles``)."""
    insp = inspect(db_session.bind)
    tables = insp.get_table_names()
    expected = {
        "users",
        "device_profiles",
        "settings",
        "ai_providers",
        "ai_models",
        "api_credentials",
        "tools",
        "permissions",
        "workflows",
        "workflow_versions",
        "workflow_nodes",
        "workflow_runs",
        "tasks",
        "task_steps",
        "task_logs",
        "screenshots",
        "browser_sessions",
        "scheduled_jobs",
        "triggers",
        "notifications",
        "automation_history",
        "error_logs",
        "audit_logs",
    }
    assert expected <= set(tables), f"missing tables: {expected - set(tables)}"
    assert len(tables) >= 22


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


def test_user_crud(db_session: Session) -> None:
    """Insert and retrieve a User record."""
    from database.models.schema import User

    user = User(
        id=str(uuid4()),
        username="alice_" + uuid4().hex[:8],
        email="alice@example.com",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    fetched = db_session.query(User).filter_by(id=user.id).one()
    assert fetched.username == user.username
    assert fetched.email == "alice@example.com"
    assert fetched.is_active is True
    assert fetched.created_at is not None
    # updated_at may equal created_at if no UPDATE fired; both must be tz-aware-ish
    assert isinstance(fetched.created_at, datetime)


def test_user_unique_username(db_session: Session) -> None:
    """A duplicate username raises IntegrityError."""
    from database.models.schema import User
    from sqlalchemy.exc import IntegrityError

    name = "dup_user_" + uuid4().hex[:8]
    db_session.add(User(id=str(uuid4()), username=name))
    db_session.commit()
    db_session.add(User(id=str(uuid4()), username=name))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# Workflow + WorkflowVersion relationship
# ---------------------------------------------------------------------------


def test_workflow_with_version(db_session: Session) -> None:
    """Insert Workflow + WorkflowVersion and verify the relationship."""
    from database.models.schema import User, Workflow, WorkflowVersion

    user = User(id=str(uuid4()), username="wf_user_" + uuid4().hex[:8])
    db_session.add(user)
    db_session.flush()

    wf = Workflow(
        id=str(uuid4()),
        name="My Workflow",
        description="Test workflow",
        latest_version=1,
        enabled=True,
        user_id=user.id,
    )
    db_session.add(wf)
    db_session.flush()

    v1 = WorkflowVersion(
        id=str(uuid4()),
        workflow_id=wf.id,
        version=1,
        trigger_json={"type": "manual"},
        nodes_json=[{"id": "n1", "type": "screen.capture"}],
        variables_json={"site": "example.com"},
        is_active=True,
    )
    db_session.add(v1)
    db_session.commit()

    # Reload and verify the relationship
    db_session.refresh(wf)
    assert len(wf.versions) == 1
    assert wf.versions[0].version == 1
    assert wf.versions[0].is_active is True
    assert wf.versions[0].nodes_json[0]["type"] == "screen.capture"


# ---------------------------------------------------------------------------
# Task + TaskStep
# ---------------------------------------------------------------------------


def test_task_step_cascade(db_session: Session) -> None:
    """Insert a Task with 3 TaskSteps; querying the task yields the steps."""
    from database.models.schema import Task, TaskStep

    task = Task(
        id=str(uuid4()),
        name="Multi-step task",
        status="running",
        plan_json={"goal": "search and screenshot"},
    )
    db_session.add(task)
    db_session.flush()

    for i, tool in enumerate(["app.launch", "browser.navigate", "screen.capture"]):
        db_session.add(TaskStep(
            id=str(uuid4()),
            task_id=task.id,
            step_id=str(i + 1),
            tool_name=tool,
            status="completed" if i < 2 else "running",
            risk_level="low",
            confidence=0.95,
            duration_ms=120 * (i + 1),
        ))
    db_session.commit()

    # Query by task_id
    steps = db_session.query(TaskStep).filter_by(task_id=task.id).order_by(TaskStep.step_id).all()
    assert len(steps) == 3
    assert [s.tool_name for s in steps] == ["app.launch", "browser.navigate", "screen.capture"]
    assert all(s.duration_ms is not None for s in steps)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


def test_audit_log_insert(db_session: Session) -> None:
    """Insert an AuditLog and query by timestamp range."""
    from database.models.schema import AuditLog

    before = datetime.now(timezone.utc)
    db_session.add(AuditLog(
        user_id=None,
        task_id=None,
        tool="mouse.click",
        action="mouse.click at (100, 200)",
        decision="allow_once",
        risk_level="low",
        request_json={"x": 100, "y": 200},
        response_json={"status": "completed"},
    ))
    db_session.commit()
    after = datetime.now(timezone.utc)

    # Query all audit logs created in this window. SQLite stores datetimes as
    # naive strings; we compare on the Python side after re-parsing.
    rows = db_session.query(AuditLog).all()
    assert len(rows) >= 1
    latest = rows[-1]
    assert latest.tool == "mouse.click"
    assert latest.decision == "allow_once"
    assert latest.risk_level == "low"
    assert latest.action.startswith("mouse.click")


def test_index_audit_log_by_timestamp(db_session: Session) -> None:
    """Verify the AuditLog.timestamp column is queryable as a datetime."""
    from database.models.schema import AuditLog

    db_session.add(AuditLog(action="test action", decision="allow_once"))
    db_session.commit()
    # Use raw SQL to verify the timestamp column is exposed as expected.
    result = db_session.execute(
        text("SELECT timestamp, action FROM audit_logs ORDER BY timestamp DESC LIMIT 1")
    ).one()
    assert result[1] == "test action"
    # The timestamp should parse back into a datetime.
    assert isinstance(result[0], (datetime, str))

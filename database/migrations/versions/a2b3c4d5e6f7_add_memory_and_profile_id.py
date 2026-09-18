"""add memories table and profile_id columns

Revision ID: a2b3c4d5e6f7
Revises: f1ad71875719
Create Date: 2026-09-18 12:00:00.000000

Adds:
1. The ``memories`` table (master prompt section 84 — long-term AI memory).
2. The ``profile_id`` column to 9 existing tables (master prompt section 49
   — multi-profile support) so workflows, permissions, runs, tasks,
   screenshots, browser sessions, scheduled jobs, triggers, and history
   rows can be scoped to a device profile.

Both operations are wrapped in ``op.batch_alter_table`` so they work on
SQLite (where ALTER TABLE is limited). The migration is idempotent: if the
table / column already exists, the operation is skipped. This makes the
migration safe to apply on a DB that was bootstrapped via
``Base.metadata.create_all()`` (which already created the schema.py
tables with profile_id columns) as well as a fresh DB that only has the
f1ad71875719 initial migration applied.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1ad71875719"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that get the new ``profile_id`` column (master prompt section 49).
_PROFILE_TABLES: tuple[str, ...] = (
    "workflows",
    "permissions",
    "workflow_runs",
    "tasks",
    "screenshots",
    "browser_sessions",
    "scheduled_jobs",
    "triggers",
    "automation_history",
)


def _existing_tables(inspector) -> set[str]:
    return set(inspector.get_table_names())


def _existing_columns(inspector, table_name: str) -> set[str]:
    try:
        return {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return set()


def _existing_indexes(inspector, table_name: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table_name)}
    except Exception:
        return set()


def upgrade() -> None:
    """Create the ``memories`` table + add ``profile_id`` to 9 tables.

    Idempotent: if the underlying objects already exist (e.g. when the DB
    was bootstrapped via Base.metadata.create_all()), the operation is a
    no-op. This keeps ``alembic upgrade head`` safe to run repeatedly.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _existing_tables(inspector)

    # ------------------------------------------------------------------
    # 1. memories table — master prompt section 84
    # ------------------------------------------------------------------
    if "memories" not in existing_tables:
        op.create_table(
            "memories",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("memory_type", sa.String(length=32), nullable=False),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("value", sa.JSON(), nullable=True),
            sa.Column(
                "source",
                sa.String(length=64),
                server_default=sa.text("'system'"),
                nullable=False,
            ),
            sa.Column("workflow_id", sa.String(length=36), nullable=True),
            sa.Column("task_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        # Re-inspect so the indexes below see the new table.
        inspector = sa.inspect(bind)

    # Indexes on memories — created idempotently.
    if "memories" in _existing_tables(inspector):
        existing_mem_ix = _existing_indexes(inspector, "memories")
        if "ix_memories_user_id" not in existing_mem_ix:
            op.create_index("ix_memories_user_id", "memories", ["user_id"])
        if "ix_memories_memory_type" not in existing_mem_ix:
            op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
        if "ix_memories_workflow_id" not in existing_mem_ix:
            op.create_index("ix_memories_workflow_id", "memories", ["workflow_id"])
        if "ix_memories_task_id" not in existing_mem_ix:
            op.create_index("ix_memories_task_id", "memories", ["task_id"])
        if "ix_memories_created_at" not in existing_mem_ix:
            op.create_index("ix_memories_created_at", "memories", ["created_at"])
        if "ix_memories_expires_at" not in existing_mem_ix:
            op.create_index("ix_memories_expires_at", "memories", ["expires_at"])

    # ------------------------------------------------------------------
    # 2. profile_id column on 9 tables — master prompt section 49
    # ------------------------------------------------------------------
    for table_name in _PROFILE_TABLES:
        if table_name not in existing_tables:
            # The parent table doesn't exist yet — skip (the schema is
            # partially initialised). The column will be added later
            # when the parent table is created via Base.metadata.create_all.
            continue
        cols = _existing_columns(inspector, table_name)
        if "profile_id" in cols:
            # Already added — nothing to do.
            continue

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "profile_id",
                    sa.String(length=36),
                    nullable=True,
                )
            )
            # Batch mode signature: create_foreign_key(constraint_name, referent_table,
            # local_cols, remote_cols, ...). source_table is implied by the batch.
            batch_op.create_foreign_key(
                f"fk_{table_name}_profile_id_device_profiles",
                "device_profiles",
                ["profile_id"],
                ["id"],
            )
            batch_op.create_index(
                f"ix_{table_name}_profile_id",
                ["profile_id"],
            )


def downgrade() -> None:
    """Drop ``profile_id`` columns + the ``memories`` table.

    Idempotent: skips missing tables / columns / indexes so the
    downgrade is safe to run from any partial state.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _existing_tables(inspector)

    # ------------------------------------------------------------------
    # 1. Drop profile_id columns + indexes from 9 tables
    # ------------------------------------------------------------------
    # Note: SQLite (and therefore batch_alter_table mode) doesn't track FK
    # constraint names the same way Postgres / MySQL does. Dropping the
    # column automatically removes any FK that references it, so we don't
    # need (and cannot use) drop_constraint here.
    for table_name in _PROFILE_TABLES:
        if table_name not in existing_tables:
            continue
        cols = _existing_columns(inspector, table_name)
        if "profile_id" not in cols:
            continue
        ix_name = f"ix_{table_name}_profile_id"
        existing_ix = _existing_indexes(inspector, table_name)
        with op.batch_alter_table(table_name) as batch_op:
            if ix_name in existing_ix:
                batch_op.drop_index(ix_name)
            batch_op.drop_column("profile_id")

    # ------------------------------------------------------------------
    # 2. Drop memories table
    # ------------------------------------------------------------------
    inspector = sa.inspect(bind)
    if "memories" in _existing_tables(inspector):
        op.drop_table("memories")

"""add teams, workspaces, policies, analytics (Phase 4 RPA)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-18 14:30:00.000000

Adds the master prompt §82 (Professional RPA) layer:

1. ``teams`` table — multi-user collaboration containers.
2. ``team_members`` table — user↔team join with role (owner/admin/member/viewer).
3. ``workspaces`` table — master prompt §50 workspaces, team-scoped.
4. ``enterprise_policies`` table — enforceable per-team policy rules
   (max_risk_level, allowed_tools, blocked_tools, allowed_domains,
   require_approval_for, max_daily_runs, data_residency).
5. ``analytics_events`` table — execution analytics for runs, tool usage,
   AI calls, permission decisions, logins, exports.
6. Adds ``team_id`` + ``default_workspace_id`` columns to ``users`` so a
   user can be a member of a primary team + have a default workspace.

All operations are wrapped in ``op.batch_alter_table`` (SQLite-safe) and
the migration is idempotent — running ``alembic upgrade head`` on a DB
that already had the schema bootstrapped via ``Base.metadata.create_all``
is a no-op for the tables that already exist.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers — idempotent introspection so the migration is safe to re-run
# ---------------------------------------------------------------------------


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


# Tables + their indexes that this migration creates (master prompt §95).
_NEW_TABLE_INDEXES: dict[str, list[tuple[str, list[str]]]] = {
    "team_members": [
        ("idx_team_members_team_id", ["team_id"]),
        ("idx_team_members_user_id", ["user_id"]),
    ],
    "workspaces": [
        ("idx_workspaces_team_id", ["team_id"]),
    ],
    "enterprise_policies": [
        ("idx_enterprise_policies_team_id", ["team_id"]),
    ],
    "analytics_events": [
        ("idx_analytics_events_team_id", ["team_id"]),
        ("idx_analytics_events_user_id", ["user_id"]),
        ("idx_analytics_events_event_type", ["event_type"]),
        ("idx_analytics_events_created_at", ["created_at"]),
    ],
}


def upgrade() -> None:
    """Create the 5 new Phase 4 tables + add 2 columns to ``users``.

    Idempotent: if a table / column / index already exists, the operation
    is skipped. This keeps ``alembic upgrade head`` safe to run on a DB
    that was bootstrapped via ``Base.metadata.create_all()`` (which
    already created the schema.py tables) as well as a fresh DB that only
    has the prior migration applied.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _existing_tables(inspector)

    # ------------------------------------------------------------------
    # 1. teams table
    # ------------------------------------------------------------------
    if "teams" not in existing_tables:
        op.create_table(
            "teams",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "owner_id",
                sa.String(length=36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("max_members", sa.Integer(), nullable=True),
            sa.Column("max_workflows", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_teams_name"),
            sa.UniqueConstraint("slug", name="uq_teams_slug"),
        )
        inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 2. team_members table
    # ------------------------------------------------------------------
    if "team_members" not in _existing_tables(inspector):
        op.create_table(
            "team_members",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column(
                "team_id",
                sa.String(length=36),
                sa.ForeignKey("teams.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=32), nullable=True),
            sa.Column("invited_at", sa.DateTime(), nullable=True),
            sa.Column("joined_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "team_id", "user_id", name="uq_team_members_team_user"
            ),
        )
        inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 3. workspaces table
    # ------------------------------------------------------------------
    if "workspaces" not in _existing_tables(inspector):
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column(
                "team_id",
                sa.String(length=36),
                sa.ForeignKey("teams.id"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_by",
                sa.String(length=36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 4. enterprise_policies table
    # ------------------------------------------------------------------
    if "enterprise_policies" not in _existing_tables(inspector):
        op.create_table(
            "enterprise_policies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column(
                "team_id",
                sa.String(length=36),
                sa.ForeignKey("teams.id"),
                nullable=False,
            ),
            sa.Column("policy_type", sa.String(length=64), nullable=False),
            sa.Column("policy_value", sa.JSON(), nullable=True),
            sa.Column("enforced", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 5. analytics_events table
    # ------------------------------------------------------------------
    if "analytics_events" not in _existing_tables(inspector):
        op.create_table(
            "analytics_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "team_id",
                sa.String(length=36),
                sa.ForeignKey("teams.id"),
                nullable=True,
            ),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("event_data", sa.JSON(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("cost_estimate", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 6. Add team_id + default_workspace_id columns to users
    # ------------------------------------------------------------------
    if "users" in _existing_tables(inspector):
        cols = _existing_columns(inspector, "users")
        if "team_id" not in cols:
            with op.batch_alter_table("users") as batch_op:
                batch_op.add_column(
                    sa.Column("team_id", sa.String(length=36), nullable=True)
                )
                batch_op.create_foreign_key(
                    "fk_users_team_id_teams",
                    "teams",
                    ["team_id"],
                    ["id"],
                )
                batch_op.create_index("ix_users_team_id", ["team_id"])
        if "default_workspace_id" not in cols:
            with op.batch_alter_table("users") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "default_workspace_id",
                        sa.String(length=36),
                        nullable=True,
                    )
                )

    # ------------------------------------------------------------------
    # 7. Indexes on the new tables (idempotent)
    # ------------------------------------------------------------------
    for table_name, indexes in _NEW_TABLE_INDEXES.items():
        if table_name not in _existing_tables(inspector):
            continue
        existing_ix = _existing_indexes(inspector, table_name)
        for ix_name, ix_cols in indexes:
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, table_name, ix_cols)
                except Exception:
                    # Index may already exist (race) — skip.
                    pass


def downgrade() -> None:
    """Drop the 5 new tables + remove the 2 new columns from ``users``.

    Idempotent: skips missing tables / columns / indexes.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _existing_tables(inspector)

    # ------------------------------------------------------------------
    # 1. Drop the new columns from users
    # ------------------------------------------------------------------
    if "users" in existing_tables:
        cols = _existing_columns(inspector, "users")
        existing_ix = _existing_indexes(inspector, "users")
        with op.batch_alter_table("users") as batch_op:
            if "default_workspace_id" in cols:
                batch_op.drop_column("default_workspace_id")
            if "team_id" in cols:
                if "ix_users_team_id" in existing_ix:
                    batch_op.drop_index("ix_users_team_id")
                batch_op.drop_column("team_id")

    # ------------------------------------------------------------------
    # 2. Drop indexes on the new tables, then drop the tables themselves
    # ------------------------------------------------------------------
    for table_name, indexes in _NEW_TABLE_INDEXES.items():
        if table_name not in existing_tables:
            continue
        existing_ix = _existing_indexes(inspector, table_name)
        for ix_name, _cols in indexes:
            if ix_name in existing_ix:
                try:
                    op.drop_index(ix_name, table_name=table_name)
                except Exception:
                    pass

    inspector = sa.inspect(bind)
    for table_name in (
        "analytics_events",
        "enterprise_policies",
        "workspaces",
        "team_members",
        "teams",
    ):
        if table_name in _existing_tables(inspector):
            op.drop_table(table_name)

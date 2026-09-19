"""add teams, workspaces, policies, analytics (Phase 4 RPA)

Revision ID: c4d5e6f7a8b9
Revises: a2b3c4d5e6f7
Create Date: 2026-09-19 10:00:00.000000

Adds the master prompt §82 (Professional RPA) layer:

1. ``teams`` table — multi-user collaboration containers.
2. ``team_members`` table — user<->team join with role
   (owner/admin/member/viewer) + status (pending/active/revoked).
3. ``workspaces`` table — master prompt §50 workspaces, team-scoped.
4. ``enterprise_policies`` table — enforceable per-team policy rules
   (max_risk_level, allowed_tools, blocked_tools, allowed_domains,
   require_approval_for, max_daily_runs, data_residency).
5. ``analytics_events`` table — execution analytics for runs, tool
   usage, AI calls, permission decisions, logins, exports.

The migration is IDEMPOTENT — every ``op.create_table`` /
``op.create_index`` call is guarded by an inspector check so running
``alembic upgrade head`` on a DB that already has the tables (e.g.
one bootstrapped via ``Base.metadata.create_all()``) is a no-op.
This keeps the upgrade safe to run on existing dev / test DBs.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Idempotent helpers — skip operations on already-existing tables / indexes
# ---------------------------------------------------------------------------


def _existing_tables(inspector) -> set[str]:
    return set(inspector.get_table_names())


def _existing_indexes(inspector, table_name: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table_name)}
    except Exception:
        return set()


# Indexes created by this migration (master prompt §95 — helpful indexes
# for analytics queries + team membership lookups).
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
    """Create the 5 new Phase 4 tables + indexes (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ------------------------------------------------------------------
    # 1. teams
    # ------------------------------------------------------------------
    if "teams" not in _existing_tables(inspector):
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
    # 2. team_members
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
    # 3. workspaces
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
    # 4. enterprise_policies
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
    # 5. analytics_events
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
    # 6. Indexes (idempotent)
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
    """Drop the 5 new tables + their indexes (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _existing_tables(inspector)

    # Drop indexes first.
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

    # Then drop tables (reverse dependency order).
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

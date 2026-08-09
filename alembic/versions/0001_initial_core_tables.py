"""initial core tables + pgvector

Revision ID: 0001
Revises:
Create Date: 2026-07-25

Enables the pgvector extension and creates the tenancy + incident lifecycle
tables (workspaces, users, incidents, incident_settings).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("slack_team_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("install_meta", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_team_id"),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slack_user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "slack_user_id", name="uq_users_workspace_slack_user"
        ),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])

    op.create_table(
        "incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slack_channel_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="open", nullable=False
        ),
        sa.Column(
            "severity",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=16), server_default="quiet", nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("mitigated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("alert_payload", postgresql.JSONB(), nullable=True),
        sa.Column("source", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_workspace_id", "incidents", ["workspace_id"])
    op.create_index("ix_incidents_slack_channel_id", "incidents", ["slack_channel_id"])

    op.create_table(
        "incident_settings",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("trigger_thresholds", postgresql.JSONB(), nullable=True),
        sa.Column("post_budget", postgresql.JSONB(), nullable=True),
        sa.Column("active_refresh_interval_s", sa.Integer(), nullable=True),
        sa.Column("mode_overrides", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("incident_id"),
    )


def downgrade() -> None:
    op.drop_table("incident_settings")
    op.drop_index("ix_incidents_slack_channel_id", table_name="incidents")
    op.drop_index("ix_incidents_workspace_id", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_table("users")
    op.drop_table("workspaces")
    # NOTE: the pgvector extension is intentionally NOT dropped here. It is a
    # foundation-level capability that later claim tables (evidence/facts/
    # hypotheses with vector(1536) embeddings) depend on, so it should not be
    # coupled to the rollback of these four tables. CREATE EXTENSION is
    # idempotent, so re-upgrading is unaffected.

"""data_erasures tombstone table
Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No FK on incident_id on purpose: the row this points at is deleted by the
    # operation that writes the tombstone. A foreign key would either block the
    # deletion or cascade the proof away with the evidence.
    op.create_table(
        "data_erasures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("incident_title", sa.String(length=512), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("row_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("export_ref", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_erasures_incident_id", "data_erasures", ["incident_id"]
    )
    op.create_index(
        "ix_data_erasures_workspace_id", "data_erasures", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_data_erasures_workspace_id", table_name="data_erasures")
    op.drop_index("ix_data_erasures_incident_id", table_name="data_erasures")
    op.drop_table("data_erasures")
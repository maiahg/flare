"""total order for the memory revision journal

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08


An identity column gives the journal a real total order that survives clock
skew and same-transaction writes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_revisions",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    )
    op.create_index(
        "ix_memory_revisions_entity_seq",
        "memory_revisions",
        ["entity_type", "entity_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_revisions_entity_seq", table_name="memory_revisions")
    op.drop_column("memory_revisions", "seq")
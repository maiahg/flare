from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import TIMESTAMP, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Embedding dimensionality — see module docstring.
EMBEDDING_DIM = 1536

# Generic envelope lifecycle (used by claim tables without a specialized enum).
CLAIM_STATUSES = ("active", "rejected", "stale", "superseded", "resolved")
DEFAULT_CLAIM_STATUS = "active"

# Envelope ``kind`` classification.
CLAIM_KINDS = ("fact", "hypothesis", "inference", "human_statement")


class ProvenanceMixin:
    """The envelope columns shared by every claim table (minus ``status``)."""

    @declared_attr
    def incident_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )

    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flare.db.base import Base, UUIDAuditMixin

MEMORY_REVISION_OPS = (
    "create",
    "update",
    "reject",
    "stale",
    "supersede",
    "resolve",
)
APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired")


class MemoryRevision(UUIDAuditMixin, Base):
    """An append-only journal entry for a mutation to a memory entity."""

    __tablename__ = "memory_revisions"
    __table_args__ = (
        Index("ix_memory_revisions_entity", "entity_type", "entity_id"),
        Index("ix_memory_revisions_entity_seq", "entity_type", "entity_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    op: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Approval(UUIDAuditMixin, Base):
    """An approval request for a subject (e.g. a mitigation option)."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_subject", "subject_type", "subject_id"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", index=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataErasure(UUIDAuditMixin, Base):
    __tablename__ = "data_erasures"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    incident_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    export_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
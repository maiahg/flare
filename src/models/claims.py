from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, UUIDAuditMixin
from src.models.provenance import DEFAULT_CLAIM_STATUS, ProvenanceMixin

# ---- Enum-ish allowed values (app-layer validated) ------------------------
EVIDENCE_SYSTEMS = (
    "metrics",
    "logs",
    "traces",
    "deploy",
    "code",
    "flags",
    "history",
    "slack",
    "demo",
)
HYPOTHESIS_STATUSES = (
    "proposed",
    "supported",
    "contradicted",
    "rejected",
    "confirmed",
)
OPEN_QUESTION_STATUSES = ("open", "answered", "dropped")
ACTION_ITEM_STATUSES = ("open", "in_progress", "done", "dropped")
TIMELINE_ENTRY_TYPES = (
    "alert",
    "deploy",
    "mitigation",
    "observation",
    "comms",
    "decision",
)
MITIGATION_RISKS = ("low", "medium", "high")
MITIGATION_REVERSIBILITY = ("reversible", "partially", "irreversible")
MITIGATION_STATUSES = (
    "proposed",
    "approved",
    "rejected",
    "applied",
    "rolled_back",
)
COMMS_AUDIENCES = ("internal", "support", "status", "exec")
COMMS_STATUSES = ("draft", "approved", "sent")
SUMMARY_SCOPES = ("current", "internal", "support", "status", "exec")
EVIDENCE_LINK_SUBJECT_TYPES = (
    "hypothesis",
    "fact",
    "mitigation_option",
    "open_question",
    "timeline_entry",
)
EVIDENCE_LINK_RELATIONS = ("supports", "contradicts", "context")


def _hnsw_index(name: str) -> Index:
    """A cosine-distance HNSW index on the ``embedding`` column.

    Only added to tables we actually query by similarity (semantic dedupe /
    retrieval): evidence, facts, hypotheses.
    """
    return Index(
        name,
        "embedding",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class Evidence(UUIDAuditMixin, ProvenanceMixin, Base):
    """An immutable observation pulled from a source system."""

    __tablename__ = "evidence"
    __table_args__ = (_hnsw_index("ix_evidence_embedding_hnsw"),)

    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    system: Mapped[str | None] = mapped_column(String(32), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool_calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    staleness_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_CLAIM_STATUS
    )


class Fact(UUIDAuditMixin, ProvenanceMixin, Base):
    """A confirmed statement of fact."""

    __tablename__ = "facts"
    __table_args__ = (_hnsw_index("ix_facts_embedding_hnsw"),)

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_CLAIM_STATUS
    )


class Hypothesis(UUIDAuditMixin, ProvenanceMixin, Base):
    """A candidate explanation, ranked and scored."""

    __tablename__ = "hypotheses"
    __table_args__ = (_hnsw_index("ix_hypotheses_embedding_hnsw"),)

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likelihood: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="proposed"
    )


class OpenQuestion(UUIDAuditMixin, ProvenanceMixin, Base):
    """An unanswered question tracked during the incident."""

    __tablename__ = "open_questions"

    question: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="open"
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)


class Decision(UUIDAuditMixin, ProvenanceMixin, Base):
    """A decision made during the incident."""

    __tablename__ = "decisions"

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_CLAIM_STATUS
    )


class ActionItem(UUIDAuditMixin, ProvenanceMixin, Base):
    """A follow-up task."""

    __tablename__ = "action_items"

    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="open"
    )
    due_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class TimelineEntry(UUIDAuditMixin, ProvenanceMixin, Base):
    """A dated entry on the incident timeline."""

    __tablename__ = "timeline_entries"

    occurred_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )
    entry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_CLAIM_STATUS
    )


class MitigationOption(UUIDAuditMixin, ProvenanceMixin, Base):
    """A proposed mitigation, with risk / reversibility / approval state."""

    __tablename__ = "mitigation_options"

    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reversibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expected_benefit: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="proposed"
    )


class CommsDraft(UUIDAuditMixin, ProvenanceMixin, Base):
    """A drafted communication for a given audience."""

    __tablename__ = "comms_drafts"

    audience: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft"
    )


# ---- Narrative (no provenance envelope) -----------------------------------
class Summary(UUIDAuditMixin, Base):
    """A regenerated summary at a given scope/version."""

    __tablename__ = "summaries"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PostmortemDraft(UUIDAuditMixin, Base):
    """A structured postmortem draft (sections + follow-ups)."""

    __tablename__ = "postmortem_drafts"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    follow_ups: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ---- Evidence linkage (polymorphic, no envelope) --------------------------
class EvidenceLink(UUIDAuditMixin, Base):
    """Links a piece of evidence to a claim it supports/contradicts/contextualizes."""

    __tablename__ = "evidence_links"
    __table_args__ = (Index("ix_evidence_links_subject", "subject_type", "subject_id"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    relation: Mapped[str | None] = mapped_column(String(16), nullable=True)
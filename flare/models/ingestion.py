from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flare.db.base import Base, UUIDAuditMixin

SIGNAL_TYPES = (
    "service",
    "symptom",
    "time_window",
    "metric",
    "log",
    "stacktrace",
    "error",
    "deploy",
    "pr",
    "commit",
    "config",
    "flag",
    "mitigation",
    "segment",
    "region",
    "plan",
    "endpoint",
    "open_question",
    "contradiction",
    "correction",
    "command",
)
TRIGGER_DECISIONS = ("trigger", "skip", "batch")


class SlackMessage(UUIDAuditMixin, Base):
    """A redacted record of a message in an incident channel."""

    __tablename__ = "slack_messages"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slack_ts: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Signal(UUIDAuditMixin, Base):
    """A structured signal extracted from a Slack message."""

    __tablename__ = "signals"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slack_messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    novel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Trigger(UUIDAuditMixin, Base):
    """The trigger-classifier decision for a Slack message."""

    __tablename__ = "triggers"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slack_messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    reasons: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
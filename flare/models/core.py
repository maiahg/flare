from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flare.db.base import Base, TimestampMixin, UUIDAuditMixin

# Enum-ish allowed values (stored as strings; validated in the app layer).
INCIDENT_STATUSES = ("open", "mitigating", "monitoring", "resolved", "closed")
INCIDENT_SEVERITIES = ("sev1", "sev2", "sev3", "sev4", "unknown")
INCIDENT_MODES = ("quiet", "scribe", "assist", "active")
ACTIVE_MODE = "active"

DEFAULT_INCIDENT_STATUS = "open"
DEFAULT_INCIDENT_SEVERITY = "unknown"
DEFAULT_INCIDENT_MODE = "quiet"


class Workspace(UUIDAuditMixin, Base):
    """A Slack workspace / tenant."""

    __tablename__ = "workspaces"

    slack_team_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    install_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    users: Mapped[list[User]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    incidents: Mapped[list[Incident]] = relationship(back_populates="workspace")


class User(UUIDAuditMixin, Base):
    """A member of a workspace."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "slack_user_id", name="uq_users_workspace_slack_user"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="users")


class Incident(UUIDAuditMixin, Base):
    """An incident and its lifecycle state."""

    __tablename__ = "incidents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slack_channel_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_INCIDENT_STATUS
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DEFAULT_INCIDENT_SEVERITY
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DEFAULT_INCIDENT_MODE
    )

    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    detected_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    mitigated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    alert_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="incidents")
    settings: Mapped[IncidentSettings | None] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        uselist=False,
    )


class IncidentSettings(TimestampMixin, Base):
    """Per-incident tunables. Primary key is the incident id (1:1)."""

    __tablename__ = "incident_settings"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    trigger_thresholds: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    post_budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    active_refresh_interval_s: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    mode_overrides: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="settings")
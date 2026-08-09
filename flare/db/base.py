from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    """Shared declarative base class for all SQLAlchemy models."""

class UUIDMixin:
    """Mixin class to add a UUID primary key column to a model."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    )

class TimestampMixin:
    """Mixin class to add created_at and updated_at timestamp columns to a model."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

class UUIDAuditMixin(UUIDMixin, TimestampMixin):
    """Mixin class to add a UUID primary key and timestamp columns to a model."""
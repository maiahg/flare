from __future__ import annotations

from itertools import chain
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from flare.memory.errors import UnmanagedWriteError
from flare.memory.repository import SANCTIONED_KEY
from flare.memory.spec import CLAIM_MODELS
from flare.models.audit import MemoryRevision

#: Claim tables plus the journal itself — nobody should forge revisions either.
GUARDED_MODELS: tuple[type[Any], ...] = (*CLAIM_MODELS, MemoryRevision)


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if session.info.get(SANCTIONED_KEY):
        return

    for obj in chain(session.new, session.deleted):
        if isinstance(obj, GUARDED_MODELS):
            verb = "deleted" if obj in session.deleted else "created"
            raise UnmanagedWriteError(
                f"{type(obj).__name__} was {verb} outside MemoryRepository. "
                "Memory tables may only change through the journaled, "
                "provenance-checked path (and claims are superseded, never "
                "deleted)."
            )

    for obj in session.dirty:
        if isinstance(obj, GUARDED_MODELS) and session.is_modified(obj):
            raise UnmanagedWriteError(
                f"{type(obj).__name__} was modified outside MemoryRepository. "
                "Use the repository so the change is journaled in "
                "memory_revisions."
            )


def install_write_guard(session: AsyncSession) -> None:
    """Reject un-journaled writes to memory tables on this session."""
    sync_session = session.sync_session
    if not event.contains(sync_session, "before_flush", _before_flush):
        event.listen(sync_session, "before_flush", _before_flush)


def remove_write_guard(session: AsyncSession) -> None:
    """Remove the guard (used by tests and bulk maintenance paths)."""
    sync_session = session.sync_session
    if event.contains(sync_session, "before_flush", _before_flush):
        event.remove(sync_session, "before_flush", _before_flush)
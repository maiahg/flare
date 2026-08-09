from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.memory.spec import OP_CREATE, entity_type
from flare.models.audit import MemoryRevision

HUMAN_ACTOR_PREFIX = "user:"

REPROPOSAL_SIMILARITY = 0.85

_WORD = re.compile(r"[a-z0-9]+")


def human_actor(user_id: str) -> str:
    """The revision actor string for a human user id."""
    return f"{HUMAN_ACTOR_PREFIX}{user_id}"


def is_human_actor(actor: str | None) -> bool:
    """True if this revision actor is a person, not an agent."""
    return bool(actor) and str(actor).startswith(HUMAN_ACTOR_PREFIX)


async def human_locked_fields(
    session: AsyncSession, *, entity_type_name: str, entity_id: uuid.UUID
) -> frozenset[str]:
    """Fields on one entity that a human has already decided."""
    rows = await session.scalars(
        select(MemoryRevision.diff).where(
            MemoryRevision.entity_type == entity_type_name,
            MemoryRevision.entity_id == entity_id,
            MemoryRevision.op != OP_CREATE,
            MemoryRevision.actor.like(f"{HUMAN_ACTOR_PREFIX}%"),
        )
    )
    locked: set[str] = set()
    for diff in rows:
        locked.update(diff or {})
    return frozenset(locked)


def normalize_claim_text(text: str | None) -> frozenset[str]:
    """The word set used to compare two claim statements."""
    return frozenset(_WORD.findall((text or "").lower()))


def same_claim(left: str | None, right: str | None) -> bool:
    """True if two statements say the same thing (word-set Jaccard)."""
    a, b = normalize_claim_text(left), normalize_claim_text(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= REPROPOSAL_SIMILARITY


async def human_rejected_statements(
    session: AsyncSession,
    *,
    model: type[Any],
    incident_id: uuid.UUID,
    field: str = "statement",
) -> list[str]:
    """Statements of this incident's claims that a *human* rejected."""
    stmt = (
        select(getattr(model, field))
        .join(
            MemoryRevision,
            MemoryRevision.entity_id == model.id,
        )
        .where(
            model.incident_id == incident_id,
            model.status == "rejected",
            MemoryRevision.entity_type == entity_type(model),
            MemoryRevision.actor.like(f"{HUMAN_ACTOR_PREFIX}%"),
            MemoryRevision.diff.has_key("status"),  # noqa: W601 - JSONB ? operator
        )
        .distinct()
    )
    return [row for row in await session.scalars(stmt) if row]


def is_human_rejected(statement: str | None, rejected: list[str]) -> str | None:
    """The rejected statement this one restates, or None."""
    for previous in rejected:
        if same_claim(statement, previous):
            return previous
    return None
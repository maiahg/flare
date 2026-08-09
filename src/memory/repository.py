from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.memory.errors import (
    EntityNotFoundError,
    ImmutableFieldError,
    InvalidStatusError,
    ProvenanceError,
    UnknownFieldError,
)
from src.memory.snapshot import diff as compute_diff
from src.memory.snapshot import snapshot
from src.memory.spec import (
    OP_CREATE,
    OP_REJECT,
    OP_RESOLVE,
    OP_STALE,
    OP_SUPERSEDE,
    OP_TO_STATUS,
    OP_UPDATE,
    allowed_statuses,
    column_names,
    default_status,
    entity_type,
    immutable_fields,
    is_claim_model,
)
from src.models.audit import MemoryRevision
from src.models.provenance import CLAIM_KINDS

#: Marker placed on ``session.info`` while the repository is writing, so the
#: optional write guard can tell sanctioned writes from stray ones.
SANCTIONED_KEY = "src.memory.sanctioned"

C = TypeVar("C")


class MemoryRepository:
    """Journaled, provenance-checked writes to the memory tables."""

    def __init__(
        self, session: AsyncSession, *, run_id: uuid.UUID | None = None
    ) -> None:
        self._session = session
        self._run_id = run_id

    # ---- public API -------------------------------------------------------

    async def create(
        self,
        model: type[C],
        *,
        incident_id: uuid.UUID,
        kind: str | None = None,
        confidence: Decimal | float | str | None = None,
        source: Mapping[str, Any] | None = None,
        created_by: str | None = None,
        actor: str | None = None,
        run_id: uuid.UUID | None = None,
        reason: str | None = None,
        **fields: Any,
    ) -> C:
        """Create a claim, rejecting an incomplete provenance envelope."""
        self._require_claim_model(model)
        checked_confidence = _validate_envelope(kind, confidence, source, created_by)

        unknown = set(fields) - column_names(model)
        if unknown:
            raise UnknownFieldError(
                f"{model.__name__} has no field(s): {', '.join(sorted(unknown))}"
            )

        status = fields.pop("status", None) or default_status(model)
        if status is not None:
            self._validate_status(model, status)

        entity = model(  # type: ignore[call-arg]
            incident_id=incident_id,
            kind=kind,
            confidence=checked_confidence,
            source=dict(source) if source is not None else None,
            created_by=created_by,
            **({"status": status} if status is not None else {}),
            **fields,
        )

        with self._sanctioned():
            self._session.add(entity)
            await self._session.flush()
            after = snapshot(entity)
            self._journal(
                model=model,
                entity_id=getattr(entity, "id"),
                incident_id=incident_id,
                op=OP_CREATE,
                before=None,
                after=after,
                actor=actor or created_by,
                run_id=run_id,
                reason=reason,
            )
            await self._session.flush()
        return entity

    async def update(
        self,
        model: type[C],
        entity_id: uuid.UUID,
        changes: Mapping[str, Any],
        *,
        actor: str,
        run_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> C:
        """Apply field changes, journaling the before/after diff."""
        return await self._mutate(
            model,
            entity_id,
            dict(changes),
            op=OP_UPDATE,
            actor=actor,
            run_id=run_id,
            reason=reason,
        )

    async def reject(
        self,
        model: type[C],
        entity_id: uuid.UUID,
        *,
        actor: str,
        reason: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> C:
        """Mark a claim rejected. The row stays queryable."""
        return await self._mutate(
            model,
            entity_id,
            {"status": OP_TO_STATUS[OP_REJECT]},
            op=OP_REJECT,
            actor=actor,
            run_id=run_id,
            reason=reason,
        )

    async def mark_stale(
        self,
        model: type[C],
        entity_id: uuid.UUID,
        *,
        actor: str,
        staleness_at: datetime | None = None,
        reason: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> C:
        """Mark a claim stale without touching its content."""
        changes: dict[str, Any] = {"status": OP_TO_STATUS[OP_STALE]}
        if "staleness_at" in column_names(model):
            changes["staleness_at"] = staleness_at or datetime.now(UTC)
        return await self._mutate(
            model,
            entity_id,
            changes,
            op=OP_STALE,
            actor=actor,
            run_id=run_id,
            reason=reason,
        )

    async def resolve(
        self,
        model: type[C],
        entity_id: uuid.UUID,
        *,
        actor: str,
        reason: str | None = None,
        run_id: uuid.UUID | None = None,
        **extra: Any,
    ) -> C:
        """Mark a claim resolved, optionally setting fields (e.g. an answer)."""
        changes: dict[str, Any] = {"status": OP_TO_STATUS[OP_RESOLVE], **extra}
        return await self._mutate(
            model,
            entity_id,
            changes,
            op=OP_RESOLVE,
            actor=actor,
            run_id=run_id,
            reason=reason,
        )

    async def supersede(
        self,
        model: type[C],
        old_id: uuid.UUID,
        new_id: uuid.UUID,
        *,
        actor: str,
        reason: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> C:
        """Point an old claim at its replacement instead of deleting it."""
        if old_id == new_id:
            raise ValueError("a claim cannot supersede itself")

        replacement = await self._session.scalar(
            select(model).where(model.id == new_id) 
        )
        if replacement is None:
            raise EntityNotFoundError(
                f"replacement {entity_type(model)} {new_id} does not exist"
            )

        return await self._mutate(
            model,
            old_id,
            {
                "status": OP_TO_STATUS[OP_SUPERSEDE],
                "superseded_by": new_id,
            },
            op=OP_SUPERSEDE,
            actor=actor,
            run_id=run_id,
            reason=reason,
            expect_incident_id=getattr(replacement, "incident_id"),
        )

    # ---- internals --------------------------------------------------------

    async def _mutate(
        self,
        model: type[C],
        entity_id: uuid.UUID,
        changes: dict[str, Any],
        *,
        op: str,
        actor: str | None,
        run_id: uuid.UUID | None,
        reason: str | None,
        expect_incident_id: uuid.UUID | None = None,
    ) -> C:
        """Locked read-modify-write plus a journal entry, in one transaction."""
        self._require_claim_model(model)
        self._validate_changes(model, changes)

        entity = await self._load_for_update(model, entity_id)
        incident_id = getattr(entity, "incident_id")
        if expect_incident_id is not None and incident_id != expect_incident_id:
            raise ValueError(
                f"cannot supersede across incidents: {incident_id} != "
                f"{expect_incident_id}"
            )

        before = snapshot(entity)
        with self._sanctioned():
            for field, value in changes.items():
                setattr(entity, field, value)
            await self._session.flush()
            after = snapshot(entity)

            delta = compute_diff(before, after)
            if not delta:
                return entity

            self._journal(
                model=model,
                entity_id=entity_id,
                incident_id=incident_id,
                op=op,
                before=before,
                after=after,
                actor=actor,
                run_id=run_id,
                reason=reason,
            )
            await self._session.flush()
        return entity

    async def _load_for_update(self, model: type[C], entity_id: uuid.UUID) -> C:
        """Row-lock the entity so concurrent mutations serialize."""
        stmt = (
            select(model)
            .where(model.id == entity_id)  # type: ignore[attr-defined]
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        entity = await self._session.scalar(stmt)
        if entity is None:
            raise EntityNotFoundError(f"{entity_type(model)} {entity_id} not found")
        return entity

    def _journal(
        self,
        *,
        model: type[Any],
        entity_id: uuid.UUID,
        incident_id: uuid.UUID,
        op: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor: str | None,
        run_id: uuid.UUID | None,
        reason: str | None,
    ) -> None:
        """Append the revision row. Caller is already inside ``_sanctioned``."""
        self._session.add(
            MemoryRevision(
                incident_id=incident_id,
                entity_type=entity_type(model),
                entity_id=entity_id,
                op=op,
                before=before,
                after=after,
                diff=compute_diff(before, after),
                actor=actor,
                run_id=run_id if run_id is not None else self._run_id,
                reason=reason,
            )
        )

    def _validate_changes(self, model: type[Any], changes: Mapping[str, Any]) -> None:
        if not changes:
            raise ValueError("no changes supplied")

        unknown = set(changes) - column_names(model)
        if unknown:
            raise UnknownFieldError(
                f"{model.__name__} has no field(s): {', '.join(sorted(unknown))}"
            )

        blocked = set(changes) & immutable_fields(model)
        if blocked:
            raise ImmutableFieldError(
                f"{model.__name__}.{sorted(blocked)[0]} is immutable "
                f"(immutable here: {', '.join(sorted(blocked))})"
            )

        if "status" in changes:
            self._validate_status(model, changes["status"])

    @staticmethod
    def _validate_status(model: type[Any], status: Any) -> None:
        valid = allowed_statuses(model)
        if status not in valid:
            raise InvalidStatusError(
                f"{status!r} is not a valid {model.__name__} status "
                f"({', '.join(sorted(valid))})"
            )

    @staticmethod
    def _require_claim_model(model: type[Any]) -> None:
        if not is_claim_model(model):
            raise TypeError(
                f"{model.__name__} is not a provenance-carrying claim model; "
                "the memory repository only writes claim tables"
            )

    @contextmanager
    def _sanctioned(self) -> Iterator[None]:
        """Mark session writes as coming from the repository."""
        self._session.info[SANCTIONED_KEY] = True
        try:
            yield
        finally:
            self._session.info.pop(SANCTIONED_KEY, None)


def _validate_envelope(
    kind: str | None,
    confidence: Decimal | float | str | None,
    source: Mapping[str, Any] | None,
    created_by: str | None,
) -> Decimal:
    """Enforce the envelope invariant, reporting all problems at once."""
    missing = [
        name
        for name, value in (
            ("kind", kind),
            ("confidence", confidence),
            ("source", source),
            ("created_by", created_by),
        )
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ProvenanceError(
            "claim is missing required provenance field(s): "
            f"{', '.join(missing)}. Every claim needs source, confidence, "
            "kind and created_by."
        )

    if kind not in CLAIM_KINDS:
        raise ProvenanceError(f"kind={kind!r} is not one of {', '.join(CLAIM_KINDS)}")

    if not isinstance(source, Mapping) or not source:
        raise ProvenanceError("source must be a non-empty object")

    try:
        value = Decimal(str(confidence))
    except (InvalidOperation, ValueError) as exc:
        raise ProvenanceError(f"confidence={confidence!r} is not a number") from exc
    if not Decimal("0") <= value <= Decimal("1"):
        raise ProvenanceError(f"confidence must be between 0.00 and 1.00, got {value}")
    return value.quantize(Decimal("0.01"))
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.events.bus import EVENT_APPROVAL_REQUESTED, Event
from flare.events.outbox import enqueue
from flare.memory import MemoryRepository
from flare.memory.spec import entity_type
from flare.models.audit import APPROVAL_STATUSES, Approval
from flare.models.claims import MitigationOption
from flare.models.core import Incident
from flare.slack.blocks import ephemeral, in_channel, mitigation_card
from flare.steering.actors import Actor
from flare.steering.errors import ConflictError, NotFoundError, ValidationError

_logger = logging.getLogger("flare.approvals")

SUBJECT_MITIGATION = entity_type(MitigationOption)

DECISIONS = ("approved", "rejected")


async def create_approval(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    requested_by: str,
    note: str | None = None,
) -> Approval:
    """Open (or return) the pending approval for a subject."""
    existing = await session.scalar(
        select(Approval).where(
            Approval.incident_id == incident_id,
            Approval.subject_type == subject_type,
            Approval.subject_id == subject_id,
        )
    )
    if existing is not None:
        return existing

    approval = Approval(
        incident_id=incident_id,
        subject_type=subject_type,
        subject_id=subject_id,
        requested_by=requested_by,
        requested_at=datetime.now(UTC),
        status="pending",
        note=note,
    )
    session.add(approval)
    await session.flush()
    enqueue(
        session,
        Event(
            event=EVENT_APPROVAL_REQUESTED,
            incident_id=incident_id,
            data={
                "approval_id": str(approval.id),
                "subject_type": subject_type,
                "subject_id": str(subject_id),
            },
        ),
    )
    return approval


async def pending_approvals(
    session: AsyncSession, incident_id: uuid.UUID
) -> list[Approval]:
    rows = await session.scalars(
        select(Approval)
        .where(Approval.incident_id == incident_id, Approval.status == "pending")
        .order_by(Approval.requested_at)
    )
    return list(rows)


async def list_approvals(
    session: AsyncSession, incident_id: uuid.UUID, *, status: str | None = None
) -> list[Approval]:
    stmt = select(Approval).where(Approval.incident_id == incident_id)
    if status is not None:
        stmt = stmt.where(Approval.status == status)
    rows = await session.scalars(stmt.order_by(Approval.created_at.desc()))
    return list(rows)


async def decide_approval(
    session: AsyncSession,
    actor: Actor,
    *,
    incident: Incident,
    approval_id: uuid.UUID,
    decision: str,
    note: str | None = None,
) -> Approval:
    """Record a human decision and release the blocked branch."""
    if decision not in DECISIONS:
        raise ValidationError(f"decision must be one of: {', '.join(DECISIONS)}")

    approval = await session.scalar(
        select(Approval).where(
            Approval.id == approval_id, Approval.incident_id == incident.id
        )
    )
    if approval is None:
        raise NotFoundError(f"approval {approval_id} not found for this incident")
    if approval.status != "pending":
        raise ConflictError(
            f"approval {approval_id} is already {approval.status}; "
            "decisions are recorded once"
        )

    repo = MemoryRepository(session)
    before = {"status": approval.status}
    approval.status = decision
    approval.decided_by = actor.ref
    approval.decided_at = datetime.now(UTC)
    if note:
        approval.note = note
    await session.flush()

    await repo.record_change(
        entity_type_name=Approval.__tablename__,
        entity_id=approval.id,
        incident_id=incident.id,
        op="update",
        before=before,
        after={"status": decision, "decided_by": actor.ref},
        actor=actor.ref,
        reason=actor.reason(f"{decision} a mitigation proposal"),
    )

    run_id: uuid.UUID | None = None
    if approval.subject_type == SUBJECT_MITIGATION and approval.subject_id:
        option = await session.get(MitigationOption, approval.subject_id)
        run_id = _run_id_of(option)
        if decision == "rejected":
            await repo.reject(
                MitigationOption,
                approval.subject_id,
                actor=actor.ref,
                reason=actor.reason("rejected a mitigation proposal"),
            )
        else:
            await repo.update(
                MitigationOption,
                approval.subject_id,
                {"status": "approved"},
                actor=actor.ref,
                reason=actor.reason("approved a mitigation proposal"),
            )
            if incident.mitigated_at is None:
                incident.mitigated_at = datetime.now(UTC)

    from flare.events.outbox import publish_pending

    await session.commit()
    await publish_pending(session)

    if run_id is not None:
        from flare.investigation.resume import resume_run

        await resume_run(run_id, {"approval_id": str(approval.id), "decision": decision})

    if decision == "approved" and approval.subject_type == SUBJECT_MITIGATION:
        await _watch_for_recovery(incident.id)

    _logger.info(
        "approval decided",
        extra={
            "approval_id": str(approval.id),
            "decision": decision,
            "actor": actor.ref,
        },
    )
    return approval


async def _watch_for_recovery(incident_id: uuid.UUID) -> None:
    """Start watching for recovery once a mitigation is approved"""
    from flare.active.scheduler import schedule_recovery_watch

    try:
        await schedule_recovery_watch(incident_id, reason="mitigation approved")
    except Exception: 
        _logger.warning("failed to schedule the recovery watch", exc_info=True)

def _run_id_of(option: MitigationOption | None) -> uuid.UUID | None:
    """The run that proposed an option, read from its provenance envelope."""
    if option is None:
        return None
    raw = (option.source or {}).get("run_id")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:  
        return None


async def mitigation_view(
    session: AsyncSession,
    incident: Incident,
    *,
    actor: Actor,
    dashboard_url: str,
) -> dict[str, Any]:
    """`/flare mitigation` — options with Approve/Reject."""
    options = list(
        await session.scalars(
            select(MitigationOption)
            .where(
                MitigationOption.incident_id == incident.id,
                MitigationOption.status.notin_(("superseded",)),
            )
            .order_by(MitigationOption.created_at.desc())
            .limit(5)
        )
    )
    if not options:
        return ephemeral(f"No mitigation options yet. Dashboard: {dashboard_url}")

    blocks: list[dict[str, Any]] = []
    for option in options:
        approval = (
            await create_approval(
                session,
                incident_id=incident.id,
                subject_type=SUBJECT_MITIGATION,
                subject_id=option.id,
                requested_by=actor.ref,
            )
            if option.approval_required
            else None
        )
        blocks.extend(
            mitigation_card(
                approval_id=approval.id if approval else option.id,
                title=option.title or "Mitigation option",
                description=option.description or "",
                risk=option.risk or "unknown",
                reversibility=option.reversibility or "unknown",
                expected_benefit=option.expected_benefit or "—",
                dashboard_url=dashboard_url,
                status=option.status,
                decided=approval.status if approval else "not required",
            )
        )
        blocks.append({"type": "divider"})

    from flare.events.outbox import publish_pending

    await session.commit()
    await publish_pending(session)
    return in_channel(f"{len(options)} mitigation options", blocks[:-1])


__all__ = [
    "APPROVAL_STATUSES",
    "DECISIONS",
    "SUBJECT_MITIGATION",
    "create_approval",
    "decide_approval",
    "list_approvals",
    "mitigation_view",
    "pending_approvals",
]
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.agents.postmortem import (
    CauseCandidate,
    EvidenceRef,
    MemoryRef,
    PostmortemAgent,
    PostmortemMemory,
    choose_cause,
    entry,
)
from flare.memory import MemoryRepository
from flare.memory.spec import entity_type
from flare.models.claims import (
    ActionItem,
    Decision,
    Evidence,
    EvidenceLink,
    Fact,
    Hypothesis,
    PostmortemDraft,
    Summary,
    TimelineEntry,
)
from flare.models.core import Incident
from flare.models.tracing import InvestigationRun
from flare.llm import LLMClient
from flare.steering.actors import Actor

_logger = logging.getLogger("flare.postmortem")

#: Rows pulled per collection. A postmortem is a document, not a data dump.
COLLECTION_LIMIT = 50

#: Statuses that keep a claim out of the draft entirely.
_EXCLUDED = ("rejected", "superseded")


async def generate_postmortem(
    session: AsyncSession,
    incident: Incident,
    *,
    actor: Actor,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> PostmortemDraft:
    """Write the next version of the incident's postmortem draft."""
    memory = await read_memory(session, incident)
    cause = choose_cause(memory.causes)

    narrative: dict[str, list[dict[str, Any]]] = {
        "impact": [],
        "contributing_factors": [],
        "root_cause_narrative": [],
    }
    dropped = 0
    degraded = llm is None
    if llm is not None:
        agent = PostmortemAgent(llm, model=model)
        try:
            narrative, dropped = await agent.run(memory, cause=cause)
        except Exception:  
            _logger.warning("postmortem narrative failed; memory-only draft",
                            exc_info=True)
            degraded = True

    sections = build_sections(
        memory, cause=cause, narrative=narrative, dropped=dropped, degraded=degraded
    )
    follow_ups = {"action_items": memory.action_items}

    previous = await session.scalar(
        select(PostmortemDraft.version)
        .where(PostmortemDraft.incident_id == incident.id)
        .order_by(PostmortemDraft.version.desc())
        .limit(1)
    )
    draft = PostmortemDraft(
        incident_id=incident.id,
        version=int(previous or 0) + 1,
        created_by=PostmortemAgent.agent_name if not degraded else actor.ref,
        sections=sections,
        follow_ups=follow_ups,
    )
    session.add(draft)
    await session.flush()

    repo = MemoryRepository(session)
    await repo.record_change(
        entity_type_name=entity_type(PostmortemDraft),
        entity_id=draft.id,
        incident_id=incident.id,
        op="create",
        before=None,
        after={"version": draft.version, "grounded": True, "degraded": degraded},
        actor=actor.ref,
        reason=actor.reason("generated a postmortem draft"),
    )
    return draft


def build_sections(
    memory: PostmortemMemory,
    *,
    cause: CauseCandidate | None,
    narrative: dict[str, list[dict[str, Any]]],
    dropped: int,
    degraded: bool,
) -> dict[str, Any]:
    impact = list(narrative.get("impact", []))
    if not impact:
        impact = [
            entry(text, memory=ref)
            for text, ref in memory.facts
            if _is_impact(text)
        ]

    root_cause: dict[str, Any] | None = None
    if cause is not None:
        root_cause = {
            "statement": cause.statement,
            "hypothesis_id": str(cause.id),
            "status": cause.status,
            "likelihood": cause.likelihood,
            "provenance": [ref.cite() for ref in cause.supporting],
            "contradicted_by": [ref.cite() for ref in cause.contradicting],
            "narrative": narrative.get("root_cause_narrative", []),
        }

    limitations = list(memory.limitations)
    if cause is None:
        limitations.insert(
            0,
            "root cause undetermined: no hypothesis in memory has supporting "
            "evidence",
        )
    if dropped:
        limitations.append(
            f"{dropped} drafted claim(s) were dropped for citing no evidence"
        )
    if degraded:
        limitations.append(
            "narrative unavailable (model not reached); sections are assembled "
            "from memory only"
        )

    return {
        "title": memory.title,
        "status": memory.status,
        "severity": memory.severity,
        "started_at": _iso(memory.started_at),
        "mitigated_at": _iso(memory.mitigated_at),
        "resolved_at": _iso(memory.resolved_at),
        "summary": (
            entry(memory.summary, memory=memory.summary_ref)
            if memory.summary and memory.summary_ref
            else None
        ),
        "impact": impact,
        "timeline": memory.timeline,
        "root_cause": root_cause,
        "contributing_factors": narrative.get("contributing_factors", []),
        "what_we_know": [entry(text, memory=ref) for text, ref in memory.facts],
        "decisions": [entry(text, memory=ref) for text, ref in memory.decisions],
        "limitations": limitations,
        "provenance": {
            "generated_by": PostmortemAgent.agent_name,
            "degraded": degraded,
            "dropped_uncited": dropped,
            "evidence_considered": len(memory.evidence),
        },
    }


async def read_memory(
    session: AsyncSession, incident: Incident
) -> PostmortemMemory:
    """Read the incident's memory into the agent's input shape."""
    summary_row = await session.scalar(
        select(Summary)
        .where(Summary.incident_id == incident.id, Summary.scope == "current")
        .order_by(Summary.version.desc())
        .limit(1)
    )
    evidence_rows = list(
        await session.scalars(
            select(Evidence)
            .where(
                Evidence.incident_id == incident.id,
                Evidence.status.notin_(_EXCLUDED),
            )
            .order_by(Evidence.observed_at.nullslast(), Evidence.created_at)
            .limit(COLLECTION_LIMIT)
        )
    )
    evidence = {row.id: _evidence_ref(row) for row in evidence_rows}

    memory = PostmortemMemory(
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        started_at=incident.started_at,
        mitigated_at=incident.mitigated_at,
        resolved_at=incident.resolved_at,
        summary=summary_row.body if summary_row is not None else None,
        summary_ref=(
            MemoryRef(
                entity_type=entity_type(Summary),
                entity_id=summary_row.id,
                created_by=summary_row.created_by,
            )
            if summary_row is not None
            else None
        ),
        evidence=list(evidence.values()),
    )
    memory.causes = await _causes(session, incident, evidence)

    for fact in await session.scalars(
        select(Fact)
        .where(Fact.incident_id == incident.id, Fact.status.notin_(_EXCLUDED))
        .order_by(Fact.created_at)
        .limit(COLLECTION_LIMIT)
    ):
        memory.facts.append((fact.statement, _memory_ref(Fact, fact)))

    for decision in await session.scalars(
        select(Decision)
        .where(Decision.incident_id == incident.id, Decision.status.notin_(_EXCLUDED))
        .order_by(Decision.created_at)
        .limit(COLLECTION_LIMIT)
    ):
        memory.decisions.append((decision.statement, _memory_ref(Decision, decision)))

    for item in await session.scalars(
        select(TimelineEntry)
        .where(
            TimelineEntry.incident_id == incident.id,
            TimelineEntry.status.notin_(_EXCLUDED),
        )
        .order_by(TimelineEntry.occurred_at.nullslast(), TimelineEntry.created_at)
        .limit(COLLECTION_LIMIT)
    ):
        memory.timeline.append(
            entry(
                item.description or "",
                memory=_memory_ref(TimelineEntry, item),
                at=_iso(item.occurred_at),
                entry_type=item.entry_type,
            )
        )

    for action in await session.scalars(
        select(ActionItem)
        .where(
            ActionItem.incident_id == incident.id,
            ActionItem.status.notin_(_EXCLUDED),
        )
        .order_by(ActionItem.created_at)
        .limit(COLLECTION_LIMIT)
    ):
        memory.action_items.append(
            entry(
                action.description,
                memory=_memory_ref(ActionItem, action),
                status=action.status,
                owner_user_id=str(action.owner_user_id) if action.owner_user_id else None,
                due_at=_iso(action.due_at),
            )
        )

    memory.limitations = await _run_limitations(session, incident)
    return memory


async def _causes(
    session: AsyncSession,
    incident: Incident,
    evidence: dict[uuid.UUID, EvidenceRef],
) -> list[CauseCandidate]:
    """Candidate causes with their support/contradiction links resolved."""
    hypotheses = list(
        await session.scalars(
            select(Hypothesis)
            .where(
                Hypothesis.incident_id == incident.id,
                Hypothesis.status.notin_(("superseded",)),
            )
            .order_by(Hypothesis.likelihood.desc().nullslast())
            .limit(COLLECTION_LIMIT)
        )
    )
    if not hypotheses:
        return []

    links = (
        await session.execute(
            select(EvidenceLink.subject_id, EvidenceLink.evidence_id, EvidenceLink.relation)
            .where(
                EvidenceLink.incident_id == incident.id,
                EvidenceLink.subject_type == "hypothesis",
                EvidenceLink.subject_id.in_([h.id for h in hypotheses]),
            )
            .order_by(EvidenceLink.created_at)
        )
    ).all()

    supporting: dict[uuid.UUID, list[EvidenceRef]] = {}
    contradicting: dict[uuid.UUID, list[EvidenceRef]] = {}
    for subject_id, evidence_id, relation in links:
        ref = evidence.get(evidence_id)
        if ref is None:
            continue
        bucket = contradicting if relation == "contradicts" else supporting
        if relation in ("supports", "contradicts"):
            bucket.setdefault(subject_id, []).append(ref)

    return [
        CauseCandidate(
            id=h.id,
            statement=h.statement,
            status=h.status,
            likelihood=float(h.likelihood) if h.likelihood is not None else None,
            supporting=tuple(supporting.get(h.id, ())),
            contradicting=tuple(contradicting.get(h.id, ())),
        )
        for h in hypotheses
    ]


async def _run_limitations(
    session: AsyncSession, incident: Incident
) -> list[str]:
    """What the investigation could not see, carried onto the draft."""
    rows = await session.scalars(
        select(InvestigationRun.limitations)
        .where(
            InvestigationRun.incident_id == incident.id,
            InvestigationRun.limitations.isnot(None),
        )
        .order_by(InvestigationRun.created_at.desc())
        .limit(10)
    )
    seen: dict[str, None] = {}
    for limitations in rows:
        for note in limitations or []:
            seen.setdefault(str(note), None)
    return list(seen)


def _evidence_ref(row: Evidence) -> EvidenceRef:
    return EvidenceRef(
        id=row.id,
        system=row.system or "unknown",
        title=row.title or "",
        body=(row.body or "")[:400],
        query=row.query,
        tool_call_id=row.tool_call_id,
        status=row.status,
    )


def _memory_ref(model: type[Any], row: Any) -> MemoryRef:
    return MemoryRef(
        entity_type=entity_type(model),
        entity_id=row.id,
        created_by=row.created_by,
        kind=row.kind,
    )


_IMPACT_WORDS = ("customer", "merchant", "user", "checkout", "order", "affected",
                 "impact", "error rate", "% of", "requests")


def _is_impact(statement: str) -> bool:
    text = statement.lower()
    return any(word in text for word in _IMPACT_WORDS)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = ["build_sections", "generate_postmortem", "read_memory"]
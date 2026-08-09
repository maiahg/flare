from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flare.agents.drafts import (
    CriticVerdict,
    EvidenceDraft,
    HypothesisDraft,
    MitigationDraft,
)
from flare.events.bus import EVENT_SUMMARY_UPDATED, Event
from flare.events.outbox import commit_and_publish, enqueue
from flare.memory import MemoryRepository, human_rejected_statements, is_human_rejected
from flare.models.claims import (
    Evidence,
    EvidenceLink,
    Hypothesis,
    MitigationOption,
    Summary,
)

_logger = logging.getLogger("flare.investigation.commit")


async def commit_memory(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    run_id: uuid.UUID,
    incident_id: uuid.UUID,
    evidence: list[EvidenceDraft],
    hypotheses: list[HypothesisDraft],
    summary: str | None,
    verdict: CriticVerdict | None,
) -> dict[str, int]:
    """Persist the staged drafts; return counts for logging."""
    downgrade = verdict.downgrade if verdict is not None else {}

    async with sessionmaker() as session:
        repo = MemoryRepository(session, run_id=run_id)

        rejected = await human_rejected_statements(
            session, model=Hypothesis, incident_id=incident_id
        )
        suppressed = 0

        # 1) evidence — kind='fact' (a directly-observed measurement), citing the
        #    exact tool call that produced it.
        ref_to_id: dict[uuid.UUID, uuid.UUID] = {}
        for draft in evidence:
            row = await repo.create(
                Evidence,
                incident_id=incident_id,
                kind="fact",
                confidence=draft.confidence,
                source={
                    "type": draft.system,
                    "tool_call_id": str(draft.tool_call_id),
                    "query": draft.query,
                },
                created_by=draft.created_by,
                title=draft.title,
                body=draft.body,
                system=draft.system,
                query=draft.query,
                result_ref=draft.result_ref,
                tool_call_id=draft.tool_call_id,
                observed_at=draft.observed_at or datetime.now(UTC),
                staleness_at=draft.staleness_at,
            )
            ref_to_id[draft.ref] = row.id

        # 2) hypotheses — kind='hypothesis'; apply any Critic confidence downgrade.
        for hdraft in hypotheses:
            previously = is_human_rejected(hdraft.statement, rejected)
            if previously is not None:
                suppressed += 1
                _logger.info(
                    "suppressed re-proposal of a human-rejected hypothesis",
                    extra={
                        "incident_id": str(incident_id),
                        "run_id": str(run_id),
                        "rejected_statement": previously,
                    },
                )
                continue
            likelihood = downgrade.get(str(hdraft.ref), hdraft.likelihood)
            hyp = await repo.create(
                Hypothesis,
                incident_id=incident_id,
                kind="hypothesis",
                confidence=likelihood,
                source={"type": "reasoning", "run_id": str(run_id)},
                created_by=hdraft.created_by,
                statement=hdraft.statement,
                rank=hdraft.rank,
                likelihood=likelihood,
            )
            # 3) evidence links (non-claim rows) — resolve draft refs → real ids.
            for ref in hdraft.supports:
                ev_id = ref_to_id.get(ref)
                if ev_id is not None:
                    session.add(
                        EvidenceLink(
                            incident_id=incident_id,
                            evidence_id=ev_id,
                            subject_type="hypothesis",
                            subject_id=hyp.id,
                            relation="supports",
                        )
                    )
            for ref in hdraft.contradicts:
                ev_id = ref_to_id.get(ref)
                if ev_id is not None:
                    session.add(
                        EvidenceLink(
                            incident_id=incident_id,
                            evidence_id=ev_id,
                            subject_type="hypothesis",
                            subject_id=hyp.id,
                            relation="contradicts",
                        )
                    )

        # 4) summary (non-claim) + its SSE event.
        if summary:
            session.add(
                Summary(
                    incident_id=incident_id,
                    scope="current",
                    body=summary,
                    created_by="SummarizerAgent",
                )
            )
            enqueue(
                session,
                Event(
                    event=EVENT_SUMMARY_UPDATED,
                    incident_id=incident_id,
                    data={"run_id": str(run_id)},
                ),
            )

        await commit_and_publish(session)

    return {
        "evidence": len(evidence),
        "hypotheses": len(hypotheses) - suppressed,
        "suppressed": suppressed,
    }

async def commit_mitigations(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    run_id: uuid.UUID,
    incident_id: uuid.UUID,
    drafts: list[MitigationDraft],
) -> list[uuid.UUID]:
    """Persist mitigation *proposals* and return their ids"""
    ids: list[uuid.UUID] = []
    async with sessionmaker() as session:
        repo = MemoryRepository(session, run_id=run_id)
        for draft in drafts:
            row = await repo.create(
                MitigationOption,
                incident_id=incident_id,
                kind="inference",
                confidence=draft.confidence,
                source={"type": "reasoning", "run_id": str(run_id)},
                created_by=draft.created_by,
                title=draft.title,
                description=draft.description,
                risk=draft.risk,
                reversibility=draft.reversibility,
                expected_benefit=draft.expected_benefit,
                approval_required=draft.approval_required,
            )
            ids.append(row.id)
        await commit_and_publish(session)
    return ids
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flare.agents.drafts import (
    VERDICT_CONTRADICTED,
    VERDICT_INCONCLUSIVE,
    VERDICT_SUPPORTED,
    CriticVerdict,
    EvidenceDraft,
    HypothesisDraft,
    MitigationDraft,
    VerificationVerdict,
)
from flare.events.bus import EVENT_SUMMARY_UPDATED, Event
from flare.events.outbox import commit_and_publish, enqueue
from flare.memory import MemoryRepository, human_rejected_statements, is_human_rejected
from flare.memory.errors import HumanAuthorityError
from flare.models.claims import (
    Evidence,
    EvidenceLink,
    Fact,
    Hypothesis,
    MitigationOption,
    Summary,
)

#: Actor recorded on verification-driven memory writes.
VERIFIER_ACTOR = "VerifierAgent"

#: Hypothesis status a verdict maps to (None = leave the status untouched).
_HYP_STATUS = {
    VERDICT_SUPPORTED: "supported",
    VERDICT_CONTRADICTED: "contradicted",
    VERDICT_INCONCLUSIVE: None,
}

#: Ad-hoc claims are recorded as hypotheses; the verdict picks the birth status.
_ADHOC_STATUS = {
    VERDICT_SUPPORTED: "supported",
    VERDICT_CONTRADICTED: "contradicted",
    VERDICT_INCONCLUSIVE: "proposed",
}

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

async def _persist_evidence(
    repo: MemoryRepository,
    *,
    incident_id: uuid.UUID,
    evidence: list[EvidenceDraft],
) -> dict[uuid.UUID, uuid.UUID]:
    """Create the staged evidence rows; map draft ref -> committed id."""
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
    return ref_to_id


async def commit_verification(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    run_id: uuid.UUID,
    incident_id: uuid.UUID,
    evidence: list[EvidenceDraft],
    target: dict[str, Any],
    verdict: VerificationVerdict,
) -> str:
    claim = str(target.get("statement") or "")
    kind = target.get("kind")
    note = ""

    async with sessionmaker() as session:
        repo = MemoryRepository(session, run_id=run_id)
        ref_to_id = await _persist_evidence(
            repo, incident_id=incident_id, evidence=evidence
        )

        if kind in ("fact", "hypothesis") and target.get("id"):
            subject_type = kind
            subject_id = uuid.UUID(str(target["id"]))
            model = Fact if kind == "fact" else Hypothesis
            note = await _record_on_existing(
                repo, model, subject_id, verdict=verdict
            )
        else:
            subject_type = "hypothesis"
            adhoc = await repo.create(
                Hypothesis,
                incident_id=incident_id,
                kind="inference",
                confidence=verdict.confidence,
                source={"type": "verification", "run_id": str(run_id)},
                created_by=VERIFIER_ACTOR,
                statement=claim,
                likelihood=verdict.confidence,
                status=_ADHOC_STATUS.get(verdict.verdict, "proposed"),
            )
            subject_id = adhoc.id

        _link_evidence(
            session,
            incident_id=incident_id,
            subject_type=subject_type,
            subject_id=subject_id,
            ref_to_id=ref_to_id,
            supports=verdict.supports,
            contradicts=verdict.contradicts,
        )
        await commit_and_publish(session)

    icon = {
        VERDICT_SUPPORTED: "verified",
        VERDICT_CONTRADICTED: "contradicted",
        VERDICT_INCONCLUSIVE: "inconclusive",
    }.get(verdict.verdict, verdict.verdict)
    summary = f"Claim {icon}: {claim}"
    if verdict.rationale:
        summary += f" — {verdict.rationale}"
    if note:
        summary += f" ({note})"
    return summary


async def _record_on_existing(
    repo: MemoryRepository,
    model: type[Any],
    entity_id: uuid.UUID,
    *,
    verdict: VerificationVerdict,
) -> str:
    """Stamp the verdict onto an existing claim; never override a human."""
    now = datetime.now(UTC)
    try:
        if model is Hypothesis:
            status = _HYP_STATUS.get(verdict.verdict)
            changes: dict[str, Any] = {"last_verified_at": now}
            if status is not None:
                changes["status"] = status
            await repo.update(
                model, entity_id, changes, actor=VERIFIER_ACTOR,
                reason=f"verification: {verdict.verdict}",
            )
        elif verdict.verdict == VERDICT_CONTRADICTED:
            await repo.mark_stale(
                model, entity_id, actor=VERIFIER_ACTOR,
                reason="verification: contradicted by evidence",
            )
        else:
            await repo.update(
                model, entity_id, {"last_verified_at": now}, actor=VERIFIER_ACTOR,
                reason=f"verification: {verdict.verdict}",
            )
    except HumanAuthorityError:
        return "a human already decided this claim; status left unchanged"
    return ""


def _link_evidence(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    ref_to_id: dict[uuid.UUID, uuid.UUID],
    supports: list[uuid.UUID],
    contradicts: list[uuid.UUID],
) -> None:
    """Attach supporting/contradicting evidence to the verified claim."""
    for relation, refs in (("supports", supports), ("contradicts", contradicts)):
        for ref in refs:
            ev_id = ref_to_id.get(ref)
            if ev_id is not None:
                session.add(
                    EvidenceLink(
                        incident_id=incident_id,
                        evidence_id=ev_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        relation=relation,
                    )
                )


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
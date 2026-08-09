from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas import (
    ActionItemRead,
    AgentTraceRead,
    CommsDraftRead,
    DecisionRead,
    EvidenceRead,
    FactRead,
    HypothesisRead,
    IncidentDetail,
    IncidentRead,
    IncidentSummaryCounts,
    MitigationOptionRead,
    OpenQuestionRead,
    PostmortemDraftRead,
    RevisionRead,
    RunDetail,
    RunRead,
    SummaryRead,
    TimelineEntryRead,
    ToolCallRead,
)
from src.db.session import get_session
from src.models.audit import MemoryRevision
from src.models.claims import (
    ActionItem,
    CommsDraft,
    Decision,
    Evidence,
    EvidenceLink,
    Fact,
    Hypothesis,
    MitigationOption,
    OpenQuestion,
    PostmortemDraft,
    Summary,
    TimelineEntry,
)
from src.models.core import Incident
from src.models.tracing import AgentTrace, InvestigationRun, ToolCall

router = APIRouter(tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

T = TypeVar("T")

#: Scope used when the caller doesn't ask for a specific one.
DEFAULT_SUMMARY_SCOPE = "current"


async def get_incident(incident_id: uuid.UUID, session: SessionDep) -> Incident:
    """Resolve an incident or 404."""
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"incident {incident_id} not found",
        )
    return incident


IncidentDep = Annotated[Incident, Depends(get_incident)]


async def _claims(
    session: AsyncSession,
    model: type[Any],
    incident_id: uuid.UUID,
    *,
    order_by: Any = None,
    **filters: Any,
) -> Sequence[Any]:
    """Fetch one incident's rows of a claim type, newest first by default."""
    stmt = select(model).where(model.incident_id == incident_id)
    for field, value in filters.items():
        if value is not None:
            stmt = stmt.where(getattr(model, field) == value)
    stmt = stmt.order_by(order_by if order_by is not None else model.created_at)
    return (await session.scalars(stmt)).all()


# ---- incidents -------------------------------------------------------------


@router.get("/incidents", response_model=list[IncidentRead])
async def list_incidents(
    session: SessionDep,
    incident_status: Annotated[str | None, Query(alias="status")] = None,
    workspace: Annotated[uuid.UUID | None, Query()] = None,
) -> Sequence[Incident]:
    """List incidents, newest first."""
    stmt = select(Incident)
    if incident_status is not None:
        stmt = stmt.where(Incident.status == incident_status)
    if workspace is not None:
        stmt = stmt.where(Incident.workspace_id == workspace)
    stmt = stmt.order_by(Incident.created_at.desc())
    return (await session.scalars(stmt)).all()


async def _current_summary(
    session: AsyncSession, incident_id: uuid.UUID, scope: str
) -> Summary | None:
    """The highest-version summary for a scope (summaries are versioned)."""
    stmt = (
        select(Summary)
        .where(Summary.incident_id == incident_id, Summary.scope == scope)
        .order_by(Summary.version.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident_detail(
    incident: IncidentDep, session: SessionDep
) -> IncidentDetail:
    """Overview: the incident, its current summary, and per-entity counts."""
    counts = IncidentSummaryCounts(
        **{
            field: await _count(session, model, incident.id)
            for field, model in (
                ("facts", Fact),
                ("evidence", Evidence),
                ("hypotheses", Hypothesis),
                ("open_questions", OpenQuestion),
                ("decisions", Decision),
                ("action_items", ActionItem),
                ("timeline_entries", TimelineEntry),
                ("mitigation_options", MitigationOption),
            )
        }
    )
    summary = await _current_summary(session, incident.id, DEFAULT_SUMMARY_SCOPE)
    return IncidentDetail(
        **IncidentRead.model_validate(incident).model_dump(),
        counts=counts,
        summary=SummaryRead.model_validate(summary) if summary else None,
    )


async def _count(
    session: AsyncSession, model: type[Any], incident_id: uuid.UUID
) -> int:
    total = await session.scalar(
        select(func.count()).select_from(model).where(model.incident_id == incident_id)
    )
    return int(total or 0)


@router.get("/incidents/{incident_id}/summary", response_model=SummaryRead)
async def get_summary(
    incident: IncidentDep,
    session: SessionDep,
    scope: Annotated[str, Query()] = DEFAULT_SUMMARY_SCOPE,
) -> Summary:
    """The current (highest-version) summary for a scope."""
    summary = await _current_summary(session, incident.id, scope)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no summary with scope {scope!r} for incident {incident.id}",
        )
    return summary


# ---- claim collections -----------------------------------------------------


@router.get("/incidents/{incident_id}/facts", response_model=list[FactRead])
async def list_facts(
    incident: IncidentDep,
    session: SessionDep,
    claim_status: Annotated[str | None, Query(alias="status")] = None,
) -> Sequence[Fact]:
    return await _claims(session, Fact, incident.id, status=claim_status)


@router.get("/incidents/{incident_id}/evidence", response_model=list[EvidenceRead])
async def list_evidence(
    incident: IncidentDep,
    session: SessionDep,
    system: Annotated[str | None, Query()] = None,
    claim_status: Annotated[str | None, Query(alias="status")] = None,
) -> Sequence[Evidence]:
    """Evidence for an incident, filterable by source system and status."""
    return await _claims(
        session, Evidence, incident.id, system=system, status=claim_status
    )


@router.get("/incidents/{incident_id}/hypotheses", response_model=list[HypothesisRead])
async def list_hypotheses(
    incident: IncidentDep,
    session: SessionDep,
    claim_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[HypothesisRead]:
    """Hypotheses with their supporting/contradicting evidence resolved.

    Evidence is attached via the polymorphic ``evidence_links`` table, so this
    resolves links in two queries rather than one per hypothesis.
    """
    hypotheses = await _claims(
        session,
        Hypothesis,
        incident.id,
        order_by=Hypothesis.rank,
        status=claim_status,
    )
    results = [HypothesisRead.model_validate(h) for h in hypotheses]
    if not results:
        return results

    by_id = {h.id: h for h in results}
    link_rows = (
        await session.execute(
            select(EvidenceLink, Evidence)
            .join(Evidence, Evidence.id == EvidenceLink.evidence_id)
            .where(
                EvidenceLink.incident_id == incident.id,
                EvidenceLink.subject_type == "hypothesis",
                EvidenceLink.subject_id.in_(by_id.keys()),
            )
            .order_by(EvidenceLink.created_at)
        )
    ).all()

    for link, evidence in link_rows:
        target = by_id.get(link.subject_id)
        if target is None:
            continue
        payload = EvidenceRead.model_validate(evidence)
        if link.relation == "contradicts":
            target.contradicting_evidence.append(payload)
        elif link.relation == "supports":
            target.supporting_evidence.append(payload)
    return results


@router.get("/incidents/{incident_id}/questions", response_model=list[OpenQuestionRead])
async def list_questions(
    incident: IncidentDep,
    session: SessionDep,
    claim_status: Annotated[str | None, Query(alias="status")] = None,
) -> Sequence[OpenQuestion]:
    return await _claims(session, OpenQuestion, incident.id, status=claim_status)


@router.get("/incidents/{incident_id}/decisions", response_model=list[DecisionRead])
async def list_decisions(
    incident: IncidentDep, session: SessionDep
) -> Sequence[Decision]:
    return await _claims(session, Decision, incident.id)


@router.get(
    "/incidents/{incident_id}/action-items", response_model=list[ActionItemRead]
)
async def list_action_items(
    incident: IncidentDep,
    session: SessionDep,
    claim_status: Annotated[str | None, Query(alias="status")] = None,
) -> Sequence[ActionItem]:
    return await _claims(session, ActionItem, incident.id, status=claim_status)


@router.get("/incidents/{incident_id}/timeline", response_model=list[TimelineEntryRead])
async def list_timeline(
    incident: IncidentDep, session: SessionDep
) -> Sequence[TimelineEntry]:
    """Timeline ordered by when things happened, not when we recorded them."""
    return await _claims(
        session, TimelineEntry, incident.id, order_by=TimelineEntry.occurred_at
    )


@router.get(
    "/incidents/{incident_id}/mitigations", response_model=list[MitigationOptionRead]
)
async def list_mitigations(
    incident: IncidentDep, session: SessionDep
) -> Sequence[MitigationOption]:
    return await _claims(session, MitigationOption, incident.id)


@router.get("/incidents/{incident_id}/comms", response_model=list[CommsDraftRead])
async def list_comms(
    incident: IncidentDep,
    session: SessionDep,
    audience: Annotated[str | None, Query()] = None,
) -> Sequence[CommsDraft]:
    return await _claims(session, CommsDraft, incident.id, audience=audience)


@router.get("/incidents/{incident_id}/postmortem", response_model=PostmortemDraftRead)
async def get_postmortem(incident: IncidentDep, session: SessionDep) -> PostmortemDraft:
    """The latest postmortem draft (drafts are versioned like summaries)."""
    draft = await session.scalar(
        select(PostmortemDraft)
        .where(PostmortemDraft.incident_id == incident.id)
        .order_by(PostmortemDraft.version.desc())
        .limit(1)
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no postmortem draft for incident {incident.id}",
        )
    return draft


# ---- runs ------------------------------------------------------------------


@router.get("/incidents/{incident_id}/runs", response_model=list[RunRead])
async def list_runs(
    incident: IncidentDep, session: SessionDep
) -> Sequence[InvestigationRun]:
    """Investigation runs, most recent first."""
    stmt = (
        select(InvestigationRun)
        .where(InvestigationRun.incident_id == incident.id)
        .order_by(InvestigationRun.created_at.desc())
    )
    return (await session.scalars(stmt)).all()


@router.get("/incidents/{incident_id}/runs/{run_id}", response_model=RunDetail)
async def get_run_detail(
    incident: IncidentDep, run_id: uuid.UUID, session: SessionDep
) -> RunDetail:
    """A run with its agent traces and each trace's tool calls."""
    run = await session.scalar(
        select(InvestigationRun).where(
            InvestigationRun.id == run_id,
            InvestigationRun.incident_id == incident.id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run {run_id} not found for incident {incident.id}",
        )

    traces = (
        await session.scalars(
            select(AgentTrace)
            .where(AgentTrace.run_id == run.id)
            .order_by(AgentTrace.seq, AgentTrace.created_at)
        )
    ).all()
    calls = (
        await session.scalars(
            select(ToolCall)
            .where(ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at)
        )
    ).all()

    detail = RunDetail.model_validate(run)
    trace_payloads = {t.id: AgentTraceRead.model_validate(t) for t in traces}
    for call in calls:
        parent = (
            trace_payloads.get(call.agent_trace_id) if call.agent_trace_id else None
        )
        if parent is not None:
            parent.tool_calls.append(ToolCallRead.model_validate(call))
    detail.agent_traces = [trace_payloads[t.id] for t in traces]
    return detail


# ---- audit -----------------------------------------------------------------


@router.get("/incidents/{incident_id}/revisions", response_model=list[RevisionRead])
async def list_revisions(
    incident: IncidentDep,
    session: SessionDep,
    entity_type: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
) -> Sequence[MemoryRevision]:
    """The memory journal for an incident, oldest first (it reads as history)."""
    stmt = select(MemoryRevision).where(MemoryRevision.incident_id == incident.id)
    if entity_type is not None:
        stmt = stmt.where(MemoryRevision.entity_type == entity_type)
    if since is not None:
        stmt = stmt.where(MemoryRevision.created_at >= since)
    stmt = stmt.order_by(MemoryRevision.created_at)
    return (await session.scalars(stmt)).all()
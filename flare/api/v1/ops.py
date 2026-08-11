from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.api.v1.deps import ActorDep
from flare.api.v1.incidents import IncidentDep, SessionDep
from flare.api.v1.schemas import (
    AgentTokenUsage,
    ErasureReceiptRead,
    ErasureRequest,
    IncidentUsage,
    RunTokenUsage,
)
from flare.budgets import incident_usage
from flare.config import get_settings
from flare.events.outbox import commit_and_publish
from flare.models.tracing import AgentTrace, InvestigationRun
from flare.retention import erase_incident, export_incident

router = APIRouter(tags=["ops"])


async def _by_agent(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> list[AgentTokenUsage]:
    """Per-agent totals across an incident's runs."""
    if not run_ids:
        return []
    totals: dict[str, dict[str, int]] = {}
    rows = await session.execute(
        select(AgentTrace.agent_name, AgentTrace.tokens).where(
            AgentTrace.run_id.in_(run_ids)
        )
    )
    for agent_name, tokens in rows:
        bucket = totals.setdefault(
            agent_name or "unknown", {"calls": 0, "in": 0, "out": 0}
        )
        bucket["calls"] += int((tokens or {}).get("calls", 0) or 0)
        bucket["in"] += int((tokens or {}).get("in", 0) or 0)
        bucket["out"] += int((tokens or {}).get("out", 0) or 0)
    return [
        AgentTokenUsage(
            agent_name=name,
            calls=values["calls"],
            tokens_in=values["in"],
            tokens_out=values["out"],
        )
        for name, values in sorted(
            totals.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"])
        )
    ]


@router.get("/incidents/{incident_id}/usage", response_model=IncidentUsage)
async def get_incident_usage(
    incident: IncidentDep, session: SessionDep
) -> IncidentUsage:
    """Token spend for an incident, per run and per agent, against its budget."""
    budget = get_settings().incident_budget
    usage = await incident_usage(session, incident.id)
    runs = list(
        await session.scalars(
            select(InvestigationRun)
            .where(InvestigationRun.incident_id == incident.id)
            .order_by(InvestigationRun.created_at)
        )
    )
    limit = budget.max_tokens
    return IncidentUsage(
        incident_id=incident.id,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        total=usage.total,
        runs=usage.runs,
        budget=limit,
        remaining=max(0, limit - usage.total) if limit else 0,
        near_cap=bool(limit) and usage.total >= limit * budget.warn_ratio,
        exhausted=bool(limit) and usage.total >= limit,
        by_run=[
            RunTokenUsage(
                run_id=r.id,
                run_type=r.run_type,
                status=r.status,
                created_at=r.created_at,
                tokens_in=r.token_in or 0,
                tokens_out=r.token_out or 0,
            )
            for r in runs
        ],
        by_agent=await _by_agent(session, [r.id for r in runs]),
    )


@router.get("/incidents/{incident_id}/export")
async def export(incident: IncidentDep, session: SessionDep) -> dict[str, Any]:
    """Everything the product holds about this incident, as one JSON document."""
    bundle = await export_incident(session, incident.id)
    return bundle.as_dict()


@router.delete(
    "/incidents/{incident_id}",
    response_model=ErasureReceiptRead,
    status_code=status.HTTP_200_OK,
)
async def erase(
    incident: IncidentDep,
    session: SessionDep,
    actor: ActorDep,
    body: ErasureRequest,
    response: Response,
) -> ErasureReceiptRead:
    """Delete an incident and everything cascading from it."""
    if not body.detail.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a deletion must state why; `detail` cannot be empty",
        )
    receipt = await erase_incident(
        session,
        incident.id,
        actor=actor.user_id,
        reason=body.reason,
        detail=body.detail,
    )
    await commit_and_publish(session)
    response.headers["X-Flare-Erasure-Id"] = str(receipt.tombstone_id)
    return ErasureReceiptRead(
        incident_id=receipt.incident_id,
        tombstone_id=receipt.tombstone_id,
        row_counts=receipt.row_counts,
        export_ref=receipt.export_ref,
    )


__all__ = ["router"]
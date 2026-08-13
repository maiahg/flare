from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.models.audit import Approval, DataErasure, MemoryRevision
from flare.models.claims import (
    ActionItem,
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
from flare.models.core import Incident, IncidentSettings
from flare.models.ingestion import Signal, SlackMessage, Trigger
from flare.models.tracing import AgentTrace, InvestigationRun, ToolCall

_logger = logging.getLogger("flare.retention")

_INCIDENT_TABLES: tuple[tuple[str, Any], ...] = (
    ("evidence", Evidence),
    ("facts", Fact),
    ("hypotheses", Hypothesis),
    ("open_questions", OpenQuestion),
    ("decisions", Decision),
    ("action_items", ActionItem),
    ("timeline_entries", TimelineEntry),
    ("mitigation_options", MitigationOption),
    ("evidence_links", EvidenceLink),
    ("summaries", Summary),
    ("postmortem_drafts", PostmortemDraft),
    ("slack_messages", SlackMessage),
    ("signals", Signal),
    ("triggers", Trigger),
    ("approvals", Approval),
    ("memory_revisions", MemoryRevision),
    ("incident_settings", IncidentSettings),
)


def _row(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in obj.__table__.columns:
        if column.name == "embedding":
            continue
        value = getattr(obj, column.name)
        if isinstance(value, (uuid.UUID, datetime)):
            value = str(value)
        out[column.name] = value
    return out


@dataclass
class ExportBundle:
    """An incident's full record, ready to write as JSON."""

    incident_id: uuid.UUID
    exported_at: datetime
    incident: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]]
    runs: list[dict[str, Any]]

    @property
    def row_counts(self) -> dict[str, int]:
        counts = {name: len(rows) for name, rows in self.tables.items() if rows}
        counts["investigation_runs"] = len(self.runs)
        counts["agent_traces"] = sum(len(r["traces"]) for r in self.runs)
        counts["tool_calls"] = sum(
            len(t["tool_calls"]) for r in self.runs for t in r["traces"]
        )
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": "flare.incident.export/1",
            "incident_id": str(self.incident_id),
            "exported_at": self.exported_at.isoformat(),
            "incident": self.incident,
            "row_counts": self.row_counts,
            "tables": self.tables,
            "runs": self.runs,
        }

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"incident-{self.incident_id}.json"
        path.write_text(json.dumps(self.as_dict(), indent=2, default=str))
        return path


async def export_incident(
    session: AsyncSession, incident_id: uuid.UUID
) -> ExportBundle:
    """Everything the product holds about one incident."""
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise LookupError(f"no incident {incident_id}")

    tables: dict[str, list[dict[str, Any]]] = {}
    for name, model in _INCIDENT_TABLES:
        rows = await session.scalars(
            select(model).where(model.incident_id == incident_id)
        )
        tables[name] = [_row(r) for r in rows]

    runs: list[dict[str, Any]] = []
    run_rows = list(
        await session.scalars(
            select(InvestigationRun)
            .where(InvestigationRun.incident_id == incident_id)
            .order_by(InvestigationRun.created_at)
        )
    )
    for run in run_rows:
        traces = list(
            await session.scalars(
                select(AgentTrace)
                .where(AgentTrace.run_id == run.id)
                .order_by(AgentTrace.seq, AgentTrace.created_at)
            )
        )
        calls_by_trace: dict[uuid.UUID | None, list[dict[str, Any]]] = {}
        for call in await session.scalars(
            select(ToolCall).where(ToolCall.run_id == run.id)
        ):
            calls_by_trace.setdefault(call.agent_trace_id, []).append(_row(call))
        runs.append(
            {
                **_row(run),
                "traces": [
                    {**_row(t), "tool_calls": calls_by_trace.get(t.id, [])}
                    for t in traces
                ],
                # Calls made outside a trace (there should be none) would
                # otherwise vanish from the export without anyone noticing.
                "untraced_tool_calls": calls_by_trace.get(None, []),
            }
        )

    return ExportBundle(
        incident_id=incident_id,
        exported_at=datetime.now(UTC),
        incident=_row(incident),
        tables=tables,
        runs=runs,
    )


@dataclass
class ErasureReceipt:
    """What was deleted, for the caller and for the tombstone."""

    incident_id: uuid.UUID
    row_counts: dict[str, int]
    export_ref: str | None
    tombstone_id: uuid.UUID


async def erase_incident(
    session: AsyncSession,
    incident_id: uuid.UUID,
    *,
    actor: str,
    reason: str = "request",
    detail: str = "",
    export_ref: str | None = None,
) -> ErasureReceipt:
    bundle = await export_incident(session, incident_id)
    counts = bundle.row_counts

    tombstone = DataErasure(
        incident_id=incident_id,
        workspace_id=bundle.incident.get("workspace_id"),
        incident_title=bundle.incident.get("title"),
        reason=reason,
        detail=detail or None,
        actor=actor,
        row_counts=counts,
        export_ref=export_ref,
    )
    session.add(tombstone)
    await session.flush()

    await session.execute(delete(Incident).where(Incident.id == incident_id))
    _logger.info(
        "incident erased",
        extra={
            "incident_id": str(incident_id),
            "actor": actor,
            "reason": reason,
            "rows": sum(counts.values()),
        },
    )
    return ErasureReceipt(
        incident_id=incident_id,
        row_counts=counts,
        export_ref=export_ref,
        tombstone_id=tombstone.id,
    )


async def expired_incidents(
    session: AsyncSession, *, older_than_days: int, limit: int = 100
) -> list[Incident]:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    rows = await session.scalars(
        select(Incident)
        .where(
            Incident.status.in_(("closed", "resolved")),
            func.coalesce(Incident.closed_at, Incident.resolved_at, Incident.updated_at)
            < cutoff,
        )
        .order_by(Incident.created_at)
        .limit(limit)
    )
    return list(rows)


__all__ = [
    "ErasureReceipt",
    "ExportBundle",
    "erase_incident",
    "expired_incidents",
    "export_incident",
]
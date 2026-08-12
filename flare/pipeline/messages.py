from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, TypedDict

from sqlalchemy import select

from flare.adaptive.novelty import load_memory_view
from flare.agents.scribe import ScribeAgent
from flare.agents.schemas import ExtractedSignal
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.events.outbox import commit_and_publish
from flare.llm import get_llm_client
from flare.memory import MemoryRepository
from flare.models.claims import Decision, Fact, OpenQuestion, TimelineEntry
from flare.models.core import Incident
from flare.models.ingestion import SlackMessage
from flare.models.provenance import HUMAN_STATEMENT_KIND
from flare.slack.posting import can_post_proactively
from flare.pipeline.mapping import plan_claims
from flare.pipeline.triage import triage_message
from flare.worker.enqueue import enqueue_adaptive_run

_logger = logging.getLogger("flare.pipeline")

_TERMINAL_STATUSES = frozenset({"resolved", "closed"})


class _Envelope(TypedDict):
    incident_id: uuid.UUID
    kind: str
    confidence: float
    source: Mapping[str, Any]
    created_by: str


async def process_message(ctx: dict, payload: dict[str, Any]) -> str:
    """arq job: Slack message -> signals -> claims -> adaptive trigger decision."""
    incident_id = uuid.UUID(payload["incident_id"])
    slack_ts = payload.get("slack_ts")
    text = payload["text"]
    user_id = payload.get("user_id")

    async with get_sessionmaker()() as session:
        # ---- idempotency: same slack_ts must not double-write
        if slack_ts is not None:
            existing = await session.scalar(
                select(SlackMessage.id).where(
                    SlackMessage.incident_id == incident_id,
                    SlackMessage.slack_ts == slack_ts,
                )
            )
            if existing is not None:
                _logger.info("duplicate slack_ts %s ignored", slack_ts)
                return "duplicate"

        incident = await session.get(Incident, incident_id)
        mode = incident.mode if incident is not None else "quiet"
        status = incident.status if incident is not None else "open"

        # ---- Scribe: persist message + signals
        scribe = ScribeAgent(get_llm_client())
        message, signal_rows = await scribe.run(
            session,
            incident_id=incident_id,
            slack_ts=slack_ts,
            user_id=user_id,
            text=text,
            raw=payload.get("raw"),
        )

        extracted = [
            ExtractedSignal(
                signal_type=r.signal_type or "",
                value=r.value or {},
                confidence=float(r.confidence or 0),
            )
            for r in signal_rows
        ]

        memory_view = await load_memory_view(
            session, incident_id, exclude_message_id=message.id
        )

        # ---- project signals -> claims, write via the memory repo
        plan = plan_claims(text, extracted)
        repo = MemoryRepository(session)

        source = {"type": "slack", "ts": slack_ts, "user": user_id}
        common: _Envelope = {
            "incident_id": incident_id,
            "kind": HUMAN_STATEMENT_KIND,
            "confidence": 0.8,
            "source": source,
            "created_by": "scribe",
        }

        for entry in plan.timeline:
            await repo.create(TimelineEntry, **common, **entry)
        for fact in plan.facts:
            await repo.create(Fact, **common, **fact)
        for q in plan.questions:
            await repo.create(OpenQuestion, **common, **q)
        for d in plan.decisions:
            await repo.create(Decision, **common, **d)

        # ---- adaptive triage: novelty -> trigger decision -> coalesce window
        triage = await triage_message(
            session,
            get_llm_client(),
            incident_id=incident_id,
            message_id=message.id,
            slack_ts=slack_ts,
            user_id=user_id,
            text=text,
            extracted=extracted,
            memory_view=memory_view,
            signal_rows=signal_rows,
        )

        # ---- commit, THEN publish the queued SSE events
        await commit_and_publish(session)

    may_auto_investigate = (
        can_post_proactively(mode) and status not in _TERMINAL_STATUSES
    )
    if triage.opened_window and may_auto_investigate:
        await enqueue_adaptive_run(
            {"incident_id": str(incident_id), "created_by": "adaptive"},
            defer_by=get_settings().adaptive.coalesce_window_s,
        )
    _logger.info(
        "message triaged",
        extra={"decision": triage.decision, "score": triage.score},
    )
    return f"ok:{triage.decision}"
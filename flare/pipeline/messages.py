from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, TypedDict

from sqlalchemy import select

from flare.agents.scribe import ScribeAgent
from flare.agents.schemas import ExtractedSignal
from flare.db.session import get_sessionmaker
from flare.events.outbox import commit_and_publish
from flare.llm import get_llm_client
from flare.memory import MemoryRepository
from flare.models.claims import Decision, Fact, OpenQuestion, TimelineEntry
from flare.models.ingestion import SlackMessage
from flare.pipeline.mapping import plan_claims

_logger = logging.getLogger("flare.pipeline")

_SOURCE_KIND = "human_statement"  # signals come from a human's Slack message


class _Envelope(TypedDict):
    incident_id: uuid.UUID
    kind: str
    confidence: float
    source: Mapping[str, Any]
    created_by: str


async def process_message(ctx: dict, payload: dict[str, Any]) -> str:
    """arq job: Slack message -> signals -> provenance-tagged claims."""
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

        # ---- Scribe: persist message + signals
        scribe = ScribeAgent(get_llm_client())
        _message, signal_rows = await scribe.run(
            session,
            incident_id=incident_id,
            slack_ts=slack_ts,
            user_id=user_id,
            text=text,
            raw=payload.get("raw"),
        )

        # ---- project signals -> claims, write via the memory repo
        extracted = [
            ExtractedSignal(
                signal_type=r.signal_type or "",
                value=r.value or {},
                confidence=float(r.confidence or 0),
            )
            for r in signal_rows
        ]
        plan = plan_claims(text, extracted)
        repo = MemoryRepository(session)

        source = {"type": "slack", "ts": slack_ts, "user": user_id}
        common: _Envelope = {
            "incident_id": incident_id,
            "kind": _SOURCE_KIND,
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

        # ---- commit, THEN publish the queued SSE events
        await commit_and_publish(session)
    return "ok"
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from flare.adaptive.novelty import (
    MemoryView,
    NoveltyVerdict,
    evaluate_novelty,
    signal_text,
)
from flare.adaptive.scoring import DECISION_TRIGGER, score_novelty
from flare.adaptive.window import add_pending, open_window
from flare.agents.schemas import ExtractedSignal
from flare.agents.trigger import TriggerClassifierAgent, is_actionable
from flare.config import get_settings
from flare.llm import LLMClient
from flare.models.ingestion import Signal, Trigger
from flare.redis import get_redis

_logger = logging.getLogger("flare.pipeline.triage")


@dataclass
class TriageResult:
    """What triage decided, for the caller to act on and for tests to assert."""

    decision: str
    score: float
    reasons: list[str]
    verdicts: list[NoveltyVerdict]
    opened_window: bool = False


def _payload(
    *,
    slack_ts: str | None,
    user_id: str | None,
    text: str,
    verdicts: list[NoveltyVerdict],
    reasons: list[str],
) -> dict[str, object]:
    """The per-message context a coalesced run is seeded with."""
    return {
        "slack_ts": slack_ts,
        "user_id": user_id,
        "text": text,
        "reasons": reasons,
        "signals": [
            {
                "type": v.signal_type,
                "text": signal_text(v.signal),
                "novel": v.novel,
                "category": v.category,
                "reason": v.reason,
                "confidence": v.signal.confidence,
            }
            for v in verdicts
        ],
    }


def mark_novelty(signal_rows: list[Signal], verdicts: list[NoveltyVerdict]) -> None:
    """Stamp ``signals.novel`` so the dashboard/evals can see what was new."""
    novel_by_key = {(v.signal_type, signal_text(v.signal)): v.novel for v in verdicts}
    for row in signal_rows:
        value = row.value or {}
        text = str(value.get("text", "")) if isinstance(value, dict) else str(value)
        row.novel = novel_by_key.get((row.signal_type or "", text))


async def triage_message(
    session: AsyncSession,
    llm: LLMClient,
    *,
    incident_id: uuid.UUID,
    message_id: uuid.UUID,
    slack_ts: str | None,
    user_id: str | None,
    text: str,
    extracted: list[ExtractedSignal],
    memory_view: MemoryView,
    signal_rows: list[Signal],
) -> TriageResult:
    """Decide whether this message deserves a run, and queue it if so."""
    settings = get_settings().adaptive

    verdicts = evaluate_novelty(extracted, memory_view, text=text)
    mark_novelty(signal_rows, verdicts)

    scored = score_novelty(
        verdicts,
        trigger_threshold=settings.trigger_threshold,
        batch_threshold=settings.batch_threshold,
    )
    classifier = TriggerClassifierAgent(llm, model=get_settings().llm.models.trigger)
    decision, reasons = await classifier.run(text=text, verdicts=verdicts, scored=scored)

    session.add(
        Trigger(
            incident_id=incident_id,
            message_id=message_id,
            decision=decision,
            score=scored.score,
            reasons={"reasons": reasons, "categories": scored.categories},
        )
    )

    result = TriageResult(
        decision=decision, score=scored.score, reasons=reasons, verdicts=verdicts
    )
    if not is_actionable(decision):
        _logger.info("message skipped by triage", extra={"reasons": reasons[:3]})
        return result

    redis = get_redis()
    await add_pending(
        redis,
        incident_id,
        _payload(
            slack_ts=slack_ts,
            user_id=user_id,
            text=text,
            verdicts=verdicts,
            reasons=reasons,
        ),
        ttl_s=settings.pending_ttl_s,
    )
    if decision == DECISION_TRIGGER:
        result.opened_window = await open_window(
            redis, incident_id, window_s=settings.coalesce_window_s
        )
    return result
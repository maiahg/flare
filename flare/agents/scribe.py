from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from flare.agents.guards import deterministic_signals
from flare.agents.schemas import ScribeOutput
from flare.llm import LLMClient, redact
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data
from flare.models.ingestion import SIGNAL_TYPES, Signal, SlackMessage

_logger = logging.getLogger("flare.agents.scribe")

_SYSTEM = f"""You are Scribe, an incident note-taker.
{UNTRUSTED_DATA_RULE}
Extract structured incident signals from the message. Return signals matching
the schema.

Pay attention to two signal types people state in plain language:
- decision: a choice the team made or committed to (e.g. "we're rolling back
  #7788", "agreed to pin the pool back to 25", "decision: revert the flag").
  Put the full decision in value.text.
- action_item: a follow-up task someone will do after the incident (e.g. "action
  item: add a pool-size regression test", "we should alert on queue depth").
  Put the full task in value.text.
Only emit these when the message actually states a decision or a follow-up —
never invent them."""

_VALID = frozenset(SIGNAL_TYPES)


class ScribeAgent:
    def __init__(self, llm: LLMClient, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    async def run(
        self,
        session: AsyncSession,
        *,
        incident_id: Any,
        slack_ts: str | None,
        user_id: str | None,
        text: str,
        raw: dict[str, Any] | None = None,
    ) -> tuple[SlackMessage, list[Signal]]:
        redacted = redact(text)

        # 1) persist the (redacted) message
        message = SlackMessage(
            incident_id=incident_id,
            slack_ts=slack_ts,
            user_id=user_id,
            text_redacted=redacted,
            raw_ref=raw,
        )
        session.add(message)
        await session.flush()  # get message.id

        # 2) LLM extraction (delimited untrusted content) + deterministic guards
        result = await self._llm.structured(
            schema=ScribeOutput,
            system=_SYSTEM,
            user=as_data(redacted, label="SLACK MESSAGE"),
            model=self._model,
            trace_name="scribe.extract",
        )
        extracted = list(result.value.signals) + deterministic_signals(redacted)

        # 3) drop invalid types, dedupe, persist signals
        seen: set[tuple[str, str]] = set()
        signals: list[Signal] = []
        for s in extracted:
            if s.signal_type not in _VALID:
                continue
            key = (s.signal_type, str(s.value))
            if key in seen:
                continue
            seen.add(key)
            row = Signal(
                incident_id=incident_id,
                message_id=message.id,
                signal_type=s.signal_type,
                value=s.value,
                confidence=s.confidence,
            )
            session.add(row)
            signals.append(row)

        await session.flush()
        return message, signals
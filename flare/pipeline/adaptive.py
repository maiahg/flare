from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.adaptive import supersede
from flare.adaptive.governor import AntiSpamGovernor, MemoryDelta
from flare.adaptive.poster import GovernedPoster
from flare.adaptive.runner import leading_hypothesis, start_adaptive_run
from flare.adaptive.window import drain, merge_context
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.investigation.graph import InvestigationPoster
from flare.models.core import Incident
from flare.models.tracing import InvestigationRun
from flare.redis import get_redis
from flare.slack.posting import InvestigationSlackPoster, SlackPoster
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.pipeline.adaptive")


async def _combine_with_superseded(
    incident_id: uuid.UUID, trigger: dict[str, Any]
) -> dict[str, Any]:
    """Supersede any in-flight run and merge its context into ``trigger``"""
    redis = get_redis()
    superseded_id = await supersede.request_supersede(redis, incident_id)
    if superseded_id is None:
        return trigger

    async with get_sessionmaker()() as session:
        run = await session.get(InvestigationRun, superseded_id)
        old = dict(run.trigger or {}) if run is not None else {}

    seen = {(s.get("type"), s.get("text")) for s in trigger.get("signals", [])}
    carried = [
        s for s in old.get("signals", []) if (s.get("type"), s.get("text")) not in seen
    ]
    trigger["signals"] = [*carried, *trigger.get("signals", [])]
    trigger["messages"] = [*old.get("messages", []), *trigger.get("messages", [])]
    trigger["superseded_run_id"] = str(superseded_id)
    _logger.info("superseding run %s with newer context", superseded_id)
    return trigger


_EXPLICIT_REASONS = frozenset(
    {"flare_investigate", "flare_validate", "manual_investigate"}
)


def _is_explicit_ask(trigger: dict[str, Any]) -> bool:
    reason = str(trigger.get("reason") or "")
    return reason in _EXPLICIT_REASONS or "command" in trigger


async def _build_poster(
    incident_id: uuid.UUID, channel: str | None, mode: str, *, force: bool = False
) -> tuple[InvestigationPoster | None, InvestigationSlackPoster | None]:
    """A mode-gated, governor-wrapped poster, or None when we can't post.

    When ``force`` is set (an explicit human ask), the poster answers regardless
    of mode and bypasses the governor — the human is owed a direct reply.
    """
    if not channel:
        return None, None
    settings = get_settings()
    try:
        inner = InvestigationSlackPoster(
            SlackPoster(),
            channel=channel,
            incident_id=incident_id,
            mode=mode,
            force=force,
        )
    except Exception: 
        _logger.warning("no Slack poster; running without channel posts")
        return None, None

    if force:
        return inner, inner

    governor = AntiSpamGovernor(
        get_redis(), incident_id=incident_id, mode=mode, settings=settings.governor
    )
    delta = MemoryDelta(previous_top=await leading_hypothesis(incident_id))
    return GovernedPoster(inner, governor, delta=delta), inner


def _merge_explicit(trigger: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
    """Fold an explicitly-supplied trigger (a `/flare investigate`) into the batch."""
    seen = {(s.get("type"), s.get("text")) for s in trigger.get("signals", [])}
    trigger["signals"] = [
        *trigger.get("signals", []),
        *(
            s
            for s in explicit.get("signals", [])
            if (s.get("type"), s.get("text")) not in seen
        ),
    ]
    trigger["messages"] = [
        *trigger.get("messages", []),
        *explicit.get("messages", []),
    ]
    trigger["reason"] = explicit.get("reason", trigger.get("reason", "adaptive"))
    if "command" in explicit:
        trigger["command"] = explicit["command"]
    return trigger


async def run_adaptive_investigation(ctx: dict, payload: dict[str, Any]) -> str:
    incident_id = uuid.UUID(payload["incident_id"])
    settings = get_settings()
    explicit: dict[str, Any] = payload.get("trigger") or {}

    items = await drain(
        get_redis(), incident_id, limit=settings.adaptive.max_coalesced_signals
    )
    if not items and not explicit:
        _logger.info("coalesce window drained empty; nothing to investigate")
        return "empty"

    trigger = merge_context(items)
    if explicit:
        trigger = _merge_explicit(trigger, explicit)
    trigger = await _combine_with_superseded(incident_id, trigger)

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        channel = incident.slack_channel_id if incident else None
        mode = incident.mode if incident else "assist"

    poster, approval_poster = await _build_poster(
        incident_id, channel, mode, force=_is_explicit_ask(trigger)
    )
    run_id = await start_adaptive_run(
        incident_id,
        trigger=trigger,
        created_by=payload.get("created_by", "adaptive"),
        scenario=payload.get("scenario", DEFAULT_SCENARIO),
        poster=poster,
        approval_poster=approval_poster,
    )
    return str(run_id)
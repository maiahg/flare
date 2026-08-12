from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from flare.agents.planner import AGENT_NAMES
from flare.db.session import get_sessionmaker
from flare.memory.authority import normalize_claim_text
from flare.models.claims import Fact, Hypothesis
from flare.models.core import Incident
from flare.pipeline.adaptive import _build_poster, _is_explicit_ask
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.pipeline.verification")

#: How many active claims a validation request is matched against.
_MATCH_CANDIDATES = 25

#: Word-set overlap (Jaccard) at or above which the typed claim is treated as
#: an existing claim rather than a fresh, ad-hoc statement.
_MATCH_THRESHOLD = 0.6


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def _resolve_target(
    session: Any, incident: Incident, claim: str
) -> dict[str, Any]:
    """Match a typed claim to an existing fact/hypothesis, else treat it as new.

    Returns ``{"kind": "fact"|"hypothesis"|None, "id": str|None,
    "statement": str}``. ``kind is None`` means no existing claim matched.
    """
    wanted = normalize_claim_text(claim)
    best: tuple[float, str, Hypothesis | Fact] | None = None

    for model in (Fact, Hypothesis):
        stmt = select(model).where(model.incident_id == incident.id)
        if model is Fact:
            stmt = stmt.where(model.status == "active")
        else:
            stmt = stmt.where(model.status.notin_(("rejected", "superseded")))
        stmt = stmt.order_by(model.created_at.desc()).limit(_MATCH_CANDIDATES)
        for row in await session.scalars(stmt):
            score = _jaccard(wanted, normalize_claim_text(row.statement))
            if best is None or score > best[0]:
                # entity_type() returns the table name (plural); the evidence
                # link + update code want the singular subject kind.
                kind = "fact" if model is Fact else "hypothesis"
                best = (score, kind, row)

    if best is not None and best[0] >= _MATCH_THRESHOLD:
        _score, kind, row = best
        return {"kind": kind, "id": str(row.id), "statement": row.statement}
    return {"kind": None, "id": None, "statement": claim}


def _trigger(claim: str, target: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    """A trigger payload that focuses the read fan-out on the claim."""
    return {
        "reason": "flare_validate",
        "command": "@flare validate",
        "user_id": user_id,
        "focus": claim,
        "messages": [{"text": claim, "user_id": user_id}],
        "signals": [
            {
                "type": "command",
                "text": claim,
                "novel": True,
                "category": "command",
                "reason": "explicit human validation request",
            }
        ],
        "verify_target": target,
    }


async def run_claim_verification(ctx: dict, payload: dict[str, Any]) -> str:
    """Verify one claim against freshly gathered evidence (`@flare validate`)."""
    from flare.adaptive.runner import start_adaptive_run

    incident_id = uuid.UUID(payload["incident_id"])
    claim = str(payload.get("claim") or "").strip()
    if not claim:
        return "empty"

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            _logger.warning("verification for unknown incident %s", incident_id)
            return "no_incident"
        channel = incident.slack_channel_id
        mode = incident.mode
        target = await _resolve_target(session, incident, claim)

    trigger = _trigger(claim, target, payload.get("created_by"))
    poster, approval_poster = await _build_poster(
        incident_id, channel, mode, force=_is_explicit_ask(trigger)
    )
    run_id = await start_adaptive_run(
        incident_id,
        trigger=trigger,
        created_by=payload.get("created_by", "system"),
        scenario=payload.get("scenario", DEFAULT_SCENARIO),
        poster=poster,
        approval_poster=approval_poster,
        run_type="verification",
        agents=list(AGENT_NAMES),
        verify_target=target,
    )
    _logger.info(
        "claim verification run started",
        extra={
            "incident_id": str(incident_id),
            "run_id": str(run_id),
            "matched": target["kind"] is not None,
        },
    )
    return str(run_id)

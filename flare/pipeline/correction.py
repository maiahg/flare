from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.db.session import get_sessionmaker
from flare.llm import get_llm_client
from flare.models.core import Incident
from flare.steering import SteeringError, SteeringService, slack_actor
from flare.steering.actors import Actor

_logger = logging.getLogger("flare.pipeline.correction")


async def reconcile_correction(ctx: dict, payload: dict[str, Any]) -> str:
    incident_id = uuid.UUID(payload["incident_id"])
    text = str(payload.get("text") or "").strip()
    if not text:
        return "empty"
    actor: Actor = slack_actor(
        str(payload.get("user_id") or "unknown"), payload.get("user_name")
    )

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            _logger.warning("correction for unknown incident %s", incident_id)
            return "no_incident"
        service = SteeringService(session, actor, llm=get_llm_client())
        try:
            outcome = await service.submit_correction(incident, correction_text=text)
        except SteeringError as exc:
            await session.rollback()
            _logger.warning("correction rejected: %s", exc)
            return "rejected"
        await service.commit()
        count = len(outcome.invalidated)

    _logger.info(
        "correction reconciled",
        extra={"incident_id": str(incident_id), "invalidated": count},
    )
    return f"ok:{count}"

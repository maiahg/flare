from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.events.outbox import commit_and_publish
from flare.llm import get_llm_client
from flare.models.core import Incident
from flare.postmortem import generate_postmortem
from flare.steering.actors import Actor, slack_actor

_logger = logging.getLogger("flare.pipeline.postmortem")


async def generate_postmortem_draft(ctx: dict, payload: dict[str, Any]) -> str:
    incident_id = uuid.UUID(payload["incident_id"])
    actor: Actor = slack_actor(
        str(payload.get("user_id") or "unknown"), payload.get("user_name")
    )
    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            _logger.warning("postmortem for unknown incident %s", incident_id)
            return "no_incident"
        draft = await generate_postmortem(
            session,
            incident,
            actor=actor,
            llm=get_llm_client(),
            model=get_settings().llm.models.postmortem,
        )
        version = draft.version
        draft_id = str(draft.id)
        await commit_and_publish(session)
    _logger.info(
        "postmortem draft written",
        extra={"incident_id": str(incident_id), "version": version},
    )
    return draft_id
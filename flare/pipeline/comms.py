from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.comms import CommsService
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.llm import get_llm_client
from flare.models.core import Incident
from flare.slack.modals import SlackModals, draft_view
from flare.steering.actors import Actor, slack_actor

_logger = logging.getLogger("flare.pipeline.comms")


def _dashboard_url(incident_id: uuid.UUID) -> str:
    base = str(get_settings().app_base_url).rstrip("/")
    return f"{base}/incidents/{incident_id}"


async def generate_comms_draft(ctx: dict, payload: dict[str, Any]) -> str:
    """Generate one audience's draft; update the waiting modal if there is one."""
    incident_id = uuid.UUID(payload["incident_id"])
    audience = str(payload["audience"])
    view_id = payload.get("view_id")
    actor: Actor = slack_actor(
        str(payload.get("user_id") or "unknown"), payload.get("user_name")
    )

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            _logger.warning("comms draft for unknown incident %s", incident_id)
            return "no_incident"
        service = CommsService(
            session,
            actor,
            llm=get_llm_client(),
            model=get_settings().llm.models.comms,
        )
        result = await service.generate(incident, audience=audience)
        await service.commit(result.draft)
        view = draft_view(
            incident_id=incident_id,
            draft_id=result.draft.id,
            audience=audience,
            body=result.draft.body or "",
            version=result.draft.version,
            status=result.draft.status,
            dashboard_url=_dashboard_url(incident_id),
            degraded=result.degraded,
        )
        draft_id = str(result.draft.id)

    if view_id:
        try:
            await SlackModals().update(view_id=str(view_id), view=view)
        except Exception:
            _logger.warning("failed to update comms modal", exc_info=True)
    return draft_id
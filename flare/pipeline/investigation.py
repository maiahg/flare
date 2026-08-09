from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.db.session import get_sessionmaker
from flare.investigation import start_initial_run
from flare.models.core import Incident
from flare.slack.posting import InvestigationSlackPoster, SlackPoster

_logger = logging.getLogger("flare.pipeline.investigation")


async def run_initial_investigation(ctx: dict, payload: dict[str, Any]) -> str:
    incident_id = uuid.UUID(payload["incident_id"])

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        channel = incident.slack_channel_id if incident else None
        mode = incident.mode if incident else "assist"

    poster: InvestigationSlackPoster | None = None
    if channel:
        try:
            poster = InvestigationSlackPoster(
                SlackPoster(),
                channel=channel,
                incident_id=incident_id,
                mode=mode,
                thread_ts=payload.get("thread_ts"),
            )
        except Exception:
            _logger.warning("no Slack poster; running without channel posts")

    run_id = await start_initial_run(
        incident_id,
        trigger=payload.get("trigger", {}),
        created_by=payload.get("created_by", "system"),
        scenario=payload.get("scenario", "db_latency_spike"),
        poster=poster,
        approval_poster=poster,
    )
    return str(run_id)
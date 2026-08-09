from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.models.core import Incident, Workspace


async def get_workspace_by_team(
    session: AsyncSession, team_id: str
) -> Workspace | None:
    return await session.scalar(
        select(Workspace).where(Workspace.slack_team_id == team_id)
    )


def bot_user_id(workspace: Workspace) -> str | None:
    """The installed bot's Slack user id (from the stored OAuth payload)."""
    meta = workspace.install_meta or {}
    value = meta.get("bot_user_id")
    return str(value) if value else None


async def adopt_or_create_incident(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    channel_id: str,
    title: str,
    severity: str = "unknown",
    description: str | None = None,
    created_by: str | None = None,
) -> Incident:
    """Return the incident tracking ``channel_id``, creating one if needed.

    An existing incident is flipped into ``assist`` mode (the mode that posts
    findings); a new one starts in ``assist`` with ``status=open``.
    """
    incident = await session.scalar(
        select(Incident).where(
            Incident.workspace_id == workspace_id,
            Incident.slack_channel_id == channel_id,
        )
    )
    if incident is None:
        incident = Incident(
            workspace_id=workspace_id,
            slack_channel_id=channel_id,
            title=title,
            description=description,
            severity=severity,
            mode="assist",
            status="open",
            started_at=datetime.now(UTC),
            created_by=created_by,
        )
        session.add(incident)
    else:
        incident.mode = "assist"
        if title:
            incident.title = title
    await session.commit()
    await session.refresh(incident)
    return incident
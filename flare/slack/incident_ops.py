from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.models.core import Incident, User, Workspace


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


async def incident_for_channel(
    session: AsyncSession, channel_id: str, *, team_id: str | None = None
) -> Incident | None:
    """The incident tracking a channel, scoped to its workspace when known."""
    if not channel_id:
        return None
    stmt = select(Incident).where(Incident.slack_channel_id == channel_id)
    if team_id:
        stmt = stmt.join(Workspace, Incident.workspace_id == Workspace.id).where(
            Workspace.slack_team_id == team_id
        )
    return await session.scalar(stmt.limit(1))


async def resolve_user(
    session: AsyncSession, workspace_id: uuid.UUID, slack_user_id: str
) -> User:
    """Find (or record) the workspace member behind a Slack user id."""
    user = await session.scalar(
        select(User).where(
            User.workspace_id == workspace_id,
            User.slack_user_id == slack_user_id,
        )
    )
    if user is not None:
        return user
    user = User(workspace_id=workspace_id, slack_user_id=slack_user_id)
    session.add(user)
    await session.flush()
    return user


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
    """Return the incident tracking ``channel_id``, creating one if needed."""
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
            mode="quiet",
            status="open",
            started_at=datetime.now(UTC),
            created_by=created_by,
        )
        session.add(incident)
    else:
        if title:
            incident.title = title
    await session.commit()
    await session.refresh(incident)
    return incident
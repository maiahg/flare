from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models import Workspace

SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"


class SlackOAuthError(Exception):
    """Raised when Slack rejects the code exchange."""


def redirect_uri() -> str:
    """The OAuth redirect URI derived from the configured app base URL."""
    base = str(get_settings().app_base_url).rstrip("/")
    return f"{base}/slack/oauth/callback"


async def exchange_code(
    code: str, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Exchange an OAuth ``code`` for an installation payload."""
    settings = get_settings()
    data = {
        "code": code,
        "client_id": settings.slack.client_id,
        "client_secret": settings.slack.client_secret.get_secret_value(),
        "redirect_uri": redirect_uri(),
    }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(SLACK_OAUTH_ACCESS_URL, data=data)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    finally:
        if owns_client:
            await client.aclose()

    if not payload.get("ok", False):
        raise SlackOAuthError(payload.get("error", "unknown_error"))
    return payload


async def persist_installation(
    session: AsyncSession, oauth_response: dict[str, Any]
) -> Workspace:
    """Upsert a ``workspaces`` row from an install payload (by team id)."""
    team = oauth_response.get("team", {}) or {}
    slack_team_id = team.get("id")
    if not slack_team_id:
        raise SlackOAuthError("missing team id in oauth response")
    name = team.get("name") or slack_team_id

    existing = (
        await session.execute(
            select(Workspace).where(Workspace.slack_team_id == slack_team_id)
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.name = name
        existing.install_meta = oauth_response
        workspace = existing
    else:
        workspace = Workspace(
            slack_team_id=slack_team_id,
            name=name,
            install_meta=oauth_response,
        )
        session.add(workspace)

    await session.commit()
    await session.refresh(workspace)
    return workspace
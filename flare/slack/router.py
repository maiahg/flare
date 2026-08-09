from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.models.core import Incident, Workspace
from flare.redis import get_redis
from flare.slack import oauth, commands as slack_commands
from flare.slack.dedupe import mark_seen
from flare.slack.events import InternalEvent, is_bot_message, normalize_event_callback
from flare.slack.incident_ops import (
    adopt_or_create_incident,
    bot_user_id,
    get_workspace_by_team,
)
from flare.slack.signature import is_valid_signature
from flare.worker.enqueue import enqueue_initial_run, enqueue_message

router = APIRouter(prefix="/slack", tags=["slack"])

_logger = logging.getLogger("flare.slack")


async def _verified_body(request: Request) -> str:
    """Read the raw body and verify the Slack signature, or raise 401."""
    body = (await request.body()).decode("utf-8")
    signing_secret = get_settings().slack.signing_secret.get_secret_value()
    valid = is_valid_signature(
        signing_secret=signing_secret,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        body=body,
        signature=request.headers.get("X-Slack-Signature"),
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Slack signature",
        )
    return body

async def _incident_for_channel(team_id: str, channel: str | None) -> uuid.UUID | None:
    """Look up a tracked incident by its Slack channel, scoped to the workspace."""
    if not channel:
        return None
    stmt = (
        select(Incident.id)
        .join(Workspace, Incident.workspace_id == Workspace.id)
        .where(
            Workspace.slack_team_id == team_id,
            Incident.slack_channel_id == channel,
        )
        .limit(1)
    )
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

@router.post("/events")
async def slack_events(request: Request) -> dict[str, Any]:
    """Events API endpoint: URL handshake + normalized event intake."""
    body = await _verified_body(request)
    payload: dict[str, Any] = json.loads(body)

    payload_type = payload.get("type")

    # 1) URL verification handshake — echo the challenge.
    if payload_type == "url_verification":
        return {"challenge": payload.get("challenge")}

    # 2) Event callbacks — dedupe, drop echoes, normalize, ACK.
    if payload_type == "event_callback":
        event_id = payload.get("event_id", "")

        if await mark_seen(get_redis(), event_id):
            _logger.info("duplicate slack event dropped", extra={"event_id": event_id})
            return {"ok": True, "status": "duplicate"}

        event: dict[str, Any] = payload.get("event", {}) or {}
        if is_bot_message(event):
            _logger.info("bot/self echo ignored", extra={"event_id": event_id})
            return {"ok": True, "status": "ignored"}

        internal = normalize_event_callback(payload)
        _logger.info(
            "slack event accepted",
            extra={
                "event_id": internal.event_id,
                "event_type": internal.event_type,
                "team_id": internal.team_id,
                "channel": internal.channel,
            },
        )
        if internal.event_type == 'message' and internal.text:
            incident_id = await _incident_for_channel(internal.team_id, internal.channel)
            if incident_id is not None:
                await enqueue_message(
                    {
                        "incident_id": str(incident_id),
                        "slack_ts": internal.ts,
                        "user_id": internal.user,
                        "text": internal.text,
                        "channel": internal.channel,
                        "team_id": internal.team_id,
                    }
                )
        elif internal.event_type == "member_joined_channel":
            await _maybe_fire_join_run(internal)
        return {"ok": True, "status": "accepted"}

    # Unknown top-level type — ACK so Slack doesn't retry.
    return {"ok": True, "status": "ignored"}


async def _maybe_fire_join_run(internal: InternalEvent) -> None:
    """When the bot joins a channel, create/adopt an incident + fire a run."""
    if not internal.channel or not internal.user:
        return
    async with get_sessionmaker()() as session:
        workspace = await get_workspace_by_team(session, internal.team_id)
        if workspace is None or internal.user != bot_user_id(workspace):
            return
        incident = await adopt_or_create_incident(
            session,
            workspace_id=workspace.id,
            channel_id=internal.channel,
            title=f"Incident in {internal.channel}",
            created_by="system",
        )
        incident_id = incident.id
    await enqueue_initial_run(
        {
            "incident_id": str(incident_id),
            "trigger": {"reason": "member_joined_channel"},
            "created_by": "system",
        }
    )


@router.post("/commands")
async def slack_commands_route(request: Request) -> dict[str, str]:
    body = await _verified_body(request)
    form = parse_qs(body)
    command = form.get("command", [""])[0]
    text = form.get("text", [""])[0]
    channel_id = form.get("channel_id", [""])[0]
    team_id = form.get("team_id", [""])[0]
    user_id = form.get("user_id", [""])[0] or None
    _logger.info("slack command received", extra={"command": command, "text": text})
    if command == "/flare":
        return await slack_commands.handle(
            text, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    return {"response_type": "ephemeral", "text": f"Unknown command `{command}`."}


@router.post("/interactions")
async def slack_interactions(request: Request) -> dict[str, bool]:
    """Interactivity endpoint (buttons/modals/menus). ACKs; no work yet."""
    body = await _verified_body(request)
    form = parse_qs(body)
    raw_payload = form.get("payload", ["{}"])[0]
    try:
        interaction: dict[str, Any] = json.loads(raw_payload)
    except json.JSONDecodeError:
        interaction = {}
    _logger.info(
        "slack interaction received",
        extra={"interaction_type": interaction.get("type")},
    )
    return {"ok": True}


@router.get("/oauth/callback")
async def slack_oauth_callback(
    code: str | None = None, error: str | None = None
) -> dict[str, Any]:
    """Install flow: exchange ``code`` and persist a ``workspaces`` row."""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slack OAuth error: {error}",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing OAuth code",
        )

    oauth_response = await oauth.exchange_code(code)
    async with get_sessionmaker()() as session:
        workspace = await oauth.persist_installation(session, oauth_response)

    _logger.info(
        "slack workspace installed",
        extra={
            "workspace_id": str(workspace.id),
            "slack_team_id": workspace.slack_team_id,
        },
    )
    return {
        "ok": True,
        "workspace_id": str(workspace.id),
        "slack_team_id": workspace.slack_team_id,
    }
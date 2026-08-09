from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, status

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.redis import get_redis
from flare.slack import oauth
from flare.slack.dedupe import mark_seen
from flare.slack.events import is_bot_message, normalize_event_callback
from flare.slack.signature import is_valid_signature

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
        # No processing yet — a later PR enqueues to the orchestrator here.
        return {"ok": True, "status": "accepted"}

    # Unknown top-level type — ACK so Slack doesn't retry.
    return {"ok": True, "status": "ignored"}


@router.post("/commands")
async def slack_commands(request: Request) -> dict[str, str]:
    """Slash command endpoint (``/flare``). ACKs ephemerally; no work yet."""
    body = await _verified_body(request)
    form = parse_qs(body)
    command = form.get("command", [""])[0]
    text = form.get("text", [""])[0]
    _logger.info(
        "slack command received",
        extra={"command": command, "text": text},
    )
    return {
        "response_type": "ephemeral",
        "text": f"Received `{command}` — flare is warming up.",
    }


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
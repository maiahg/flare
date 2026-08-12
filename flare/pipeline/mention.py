from __future__ import annotations

import logging
from typing import Any

from flare.slack.commands import handle_mention
from flare.slack.posting import SlackPoster

_logger = logging.getLogger("flare.pipeline.mention")


async def handle_mention_job(ctx: dict, payload: dict[str, Any]) -> str:
    """Answer an `@flare <action>` mention publicly in the channel."""
    channel = str(payload.get("channel") or "")
    text = str(payload.get("text") or "").strip()
    if not channel or not text:
        return "empty"
    team_id = str(payload.get("team_id") or "")
    user_id = payload.get("user_id")

    result = await handle_mention(
        text, channel_id=channel, team_id=team_id, user_id=user_id
    )
    body = str(result.get("text") or "")
    blocks = result.get("blocks")
    try:
        await SlackPoster().post_message(channel, body, blocks=blocks)
    except Exception:  # noqa: BLE001 - dev may have no bot token
        _logger.warning("mention reply post failed", extra={"channel": channel})
        return "post_failed"
    return "ok"

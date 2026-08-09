from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.models.claims import TimelineEntry
from flare.models.core import INCIDENT_MODES, Incident

_TIMELINE_N = 10


@dataclass(frozen=True)
class ParsedCommand:
    action: str
    args: list[str]


def parse(text: str) -> ParsedCommand:
    parts = (text or "").strip().split()
    if not parts:
        return ParsedCommand(action="help", args=[])
    return ParsedCommand(action=parts[0].lower(), args=parts[1:])


def _ephemeral(text: str) -> dict[str, str]:
    return {"response_type": "ephemeral", "text": text}


async def handle(command_text: str, *, channel_id: str) -> dict[str, str]:
    cmd = parse(command_text)
    if cmd.action == "mode":
        return await _handle_mode(cmd.args, channel_id=channel_id)
    if cmd.action == "timeline":
        return await _handle_timeline(channel_id=channel_id)
    return _ephemeral(
        "Usage: `/flare mode <quiet|scribe|assist|active>` or `/flare timeline`"
    )


async def _handle_mode(args: list[str], *, channel_id: str) -> dict[str, str]:
    if not args or args[0] not in INCIDENT_MODES:
        return _ephemeral(
            f"mode must be one of: {', '.join(INCIDENT_MODES)}"
        )
    new_mode = args[0]
    async with get_sessionmaker()() as session:
        incident = await session.scalar(
            select(Incident).where(Incident.slack_channel_id == channel_id)
        )
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        incident.mode = new_mode
        await session.commit()
        # (optional) emit an SSE event via the outbox here
    return _ephemeral(f"Mode set to *{new_mode}*.")


async def _handle_timeline(*, channel_id: str) -> dict[str, str]:
    async with get_sessionmaker()() as session:
        incident = await session.scalar(
            select(Incident).where(Incident.slack_channel_id == channel_id)
        )
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        rows = list(
            await session.scalars(
                select(TimelineEntry)
                .where(TimelineEntry.incident_id == incident.id)
                .order_by(TimelineEntry.occurred_at.desc().nullslast())
                .limit(_TIMELINE_N)
            )
        )
    base = str(get_settings().app_base_url).rstrip("/")
    link = f"{base}/incidents/{incident.id}"
    if not rows:
        return _ephemeral(f"No timeline entries yet. Dashboard: {link}")
    lines = "\n".join(f"• {r.description}" for r in rows)
    return _ephemeral(f"*Latest timeline*\n{lines}\n\nFull dashboard: {link}")
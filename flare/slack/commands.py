from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.models.claims import TimelineEntry
from flare.models.core import INCIDENT_MODES, INCIDENT_SEVERITIES, Incident
from flare.slack.incident_ops import adopt_or_create_incident, get_workspace_by_team
from flare.slack.posting import SlackPoster, post_incident_card
from flare.worker.enqueue import enqueue_adaptive_run, enqueue_initial_run

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


async def handle(
    command_text: str,
    *,
    channel_id: str,
    team_id: str = "",
    user_id: str | None = None,
) -> dict[str, str]:
    cmd = parse(command_text)
    if cmd.action == "start":
        return await _handle_start(
            cmd.args, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action in ("investigate", "validate"):
        return await _handle_investigate(
            cmd.action, cmd.args, channel_id=channel_id, user_id=user_id
        )
    if cmd.action == "mode":
        return await _handle_mode(cmd.args, channel_id=channel_id)
    if cmd.action == "timeline":
        return await _handle_timeline(channel_id=channel_id)
    return _ephemeral(
        "Usage: `/flare start \"title\" [--sev sevN] [--desc ...]`, "
        "`/flare investigate <what>`, `/flare validate <claim>`, "
        "`/flare mode <quiet|scribe|assist|active>`, or `/flare timeline`"
    )


@dataclass(frozen=True)
class _StartArgs:
    title: str
    severity: str
    description: str | None


def _parse_start(args: list[str]) -> _StartArgs:
    """Parse `"title" [--sev sevN] [--desc ...]` from whitespace-split tokens."""
    title_parts: list[str] = []
    severity = "unknown"
    description: str | None = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--sev" and i + 1 < len(args):
            candidate = args[i + 1].lower()
            severity = candidate if candidate in INCIDENT_SEVERITIES else "unknown"
            i += 2
        elif token == "--desc":
            description = " ".join(args[i + 1 :]).strip() or None
            break
        else:
            title_parts.append(token)
            i += 1
    title = " ".join(title_parts).strip().strip('"').strip("'")
    return _StartArgs(title=title or "Untitled incident", severity=severity, description=description)


async def _handle_start(
    args: list[str], *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, str]:
    parsed = _parse_start(args)
    async with get_sessionmaker()() as session:
        workspace = await get_workspace_by_team(session, team_id)
        if workspace is None:
            return _ephemeral("Flare isn't installed in this workspace.")
        incident = await adopt_or_create_incident(
            session,
            workspace_id=workspace.id,
            channel_id=channel_id,
            title=parsed.title,
            severity=parsed.severity,
            description=parsed.description,
            created_by=user_id,
        )
        incident_id = incident.id

    thread_ts: str | None = None
    try:
        thread_ts = await post_incident_card(
            SlackPoster(), channel=channel_id, title=parsed.title, severity=parsed.severity
        )
    except Exception:  # noqa: BLE001 - don't fail the command on a posting error
        thread_ts = None

    await enqueue_initial_run(
        {
            "incident_id": str(incident_id),
            "trigger": {
                "reason": "flare_start",
                "command": "/flare start",
                "user_id": user_id,
            },
            "created_by": user_id or "system",
            "thread_ts": thread_ts,
        }
    )
    return _ephemeral(f"Started investigation for *{parsed.title}*. Investigating…")


async def _handle_investigate(
    action: str, args: list[str], *, channel_id: str, user_id: str | None
) -> dict[str, str]:
    """`/flare investigate|validate <text>` — the rule floor's explicit ask"""
    focus = " ".join(args).strip()
    async with get_sessionmaker()() as session:
        incident = await session.scalar(
            select(Incident).where(Incident.slack_channel_id == channel_id)
        )
        if incident is None:
            return _ephemeral(
                "No flare incident is tracking this channel. Try `/flare start`."
            )
        incident_id = incident.id

    await enqueue_adaptive_run(
        {
            "incident_id": str(incident_id),
            "created_by": user_id or "system",
            "trigger": {
                "reason": f"flare_{action}",
                "command": f"/flare {action}",
                "user_id": user_id,
                "messages": [{"text": focus, "user_id": user_id}],
                "signals": [
                    {
                        "type": "command",
                        "text": focus or f"/flare {action}",
                        "novel": True,
                        "category": "command",
                        "reason": "explicit human request",
                    }
                ],
            },
        }
    )
    return _ephemeral(f"On it — {action}ing{f' *{focus}*' if focus else ''}…")


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
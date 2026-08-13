from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from flare.approvals import mitigation_view
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.models.claims import TimelineEntry
from flare.models.core import (
    INCIDENT_MODES,
    INCIDENT_SEVERITIES,
    INCIDENT_STATUSES,
    Incident,
)
from flare.slack import views
from flare.slack.blocks import ephemeral
from flare.slack.incident_ops import (
    adopt_or_create_incident,
    get_workspace_by_team,
    incident_for_channel,
)
from flare.slack.posting import SlackPoster, post_incident_card
from flare.steering import SteeringService, slack_actor
from flare.worker.enqueue import (
    enqueue_adaptive_run,
    enqueue_claim_verification,
    enqueue_correction,
    enqueue_initial_run,
    enqueue_postmortem,
)

_TIMELINE_N = 10

_READ_COMMANDS = ("hypotheses", "evidence", "questions", "decisions", "brief",
                  "dashboard", "timeline")

_USAGE = (
    "Usage: `@flare start \"title\" [--sev sevN] [--desc ...]`, "
    "`@flare investigate <what>`, `@flare validate <claim>`, "
    "`@flare correct \"what's wrong\"`, "
    "`@flare mode <quiet|scribe|assist|active>`, "
    "`@flare status <open|mitigating|monitoring|resolved|closed>`, "
    "`@flare mitigation`, `@flare postmortem`, or a read: "
    "`@flare hypotheses|evidence|questions|decisions|timeline|brief|dashboard`"
)


@dataclass(frozen=True)
class ParsedCommand:
    action: str
    args: list[str]


def parse(text: str) -> ParsedCommand:
    parts = (text or "").strip().split()
    if not parts:
        return ParsedCommand(action="help", args=[])
    return ParsedCommand(action=parts[0].lower(), args=parts[1:])


def _ephemeral(text: str) -> dict[str, Any]:
    return ephemeral(text)


async def handle_mention(
    command_text: str,
    *,
    channel_id: str,
    channel_name: str | None = None,
    team_id: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    result = await handle(
        command_text,
        channel_id=channel_id,
        channel_name=channel_name,
        team_id=team_id,
        user_id=user_id,
    )
    # Force the answer visible to everyone — the whole point of the mention.
    result["response_type"] = "in_channel"
    return result


def _dashboard_url(incident_id: Any) -> str:
    base = str(get_settings().dashboard_base_url).rstrip("/")
    return f"{base}/incidents/{incident_id}"


async def handle(
    command_text: str,
    *,
    channel_id: str,
    channel_name: str | None = None,
    team_id: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    cmd = parse(command_text)
    if cmd.action == "start":
        return await _handle_start(
            cmd.args,
            channel_id=channel_id,
            channel_name=channel_name,
            team_id=team_id,
            user_id=user_id,
        )
    if cmd.action == "investigate":
        return await _handle_investigate(
            cmd.action, cmd.args, channel_id=channel_id, team_id=team_id,
            user_id=user_id,
        )
    if cmd.action == "validate":
        return await _handle_validate(
            cmd.args, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action == "mode":
        return await _handle_mode(
            cmd.args, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action == "status":
        return await _handle_status(
            cmd.args, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action == "correct":
        return await _handle_correct(
            cmd.args, channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action == "mitigation":
        return await _handle_mitigation(
            channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action == "postmortem":
        return await _handle_postmortem(
            channel_id=channel_id, team_id=team_id, user_id=user_id
        )
    if cmd.action in _READ_COMMANDS:
        return await _handle_read(
            cmd.action, cmd.args, channel_id=channel_id, team_id=team_id
        )
    return _ephemeral(_USAGE)


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
    return _StartArgs(
        title=title or "Untitled incident", severity=severity, description=description
    )


async def _handle_start(
    args: list[str],
    *,
    channel_id: str,
    channel_name: str | None = None,
    team_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    parsed = _parse_start(args)
    async with get_sessionmaker()() as session:
        workspace = await get_workspace_by_team(session, team_id)
        if workspace is None:
            return _ephemeral("Flare isn't installed in this workspace.")
        incident = await adopt_or_create_incident(
            session,
            workspace_id=workspace.id,
            channel_id=channel_id,
            channel_name=channel_name,
            title=parsed.title,
            severity=parsed.severity,
            description=parsed.description,
            created_by=user_id,
        )
        incident_id = incident.id

    thread_ts: str | None = None
    try:
        thread_ts = await post_incident_card(
            SlackPoster(),
            channel=channel_id,
            title=parsed.title,
            severity=parsed.severity,
            dashboard_url=_dashboard_url(incident_id),
        )
    except Exception: 
        thread_ts = None

    await enqueue_initial_run(
        {
            "incident_id": str(incident_id),
            "trigger": {
                "reason": "flare_start",
                "command": "@flare start",
                "user_id": user_id,
            },
            "created_by": user_id or "system",
            "thread_ts": thread_ts,
        }
    )
    return _ephemeral(f"Started investigation for *{parsed.title}*. Investigating…")


async def _handle_investigate(
    action: str,
    args: list[str],
    *,
    channel_id: str,
    team_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """`@flare investigate <text>` — the rule floor's explicit ask"""
    focus = " ".join(args).strip()
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral(
                "No flare incident is tracking this channel. Try `@flare start`."
            )
        actor = slack_actor(user_id or "unknown")
        service = SteeringService(session, actor)
        request = await service.request_investigation(incident, focus=focus or action)
        trigger = request.trigger(actor)
        trigger["reason"] = f"flare_{action}"
        trigger["command"] = f"@flare {action}"
        incident_id = incident.id
        service.defer(
            lambda: enqueue_adaptive_run(
                {
                    "incident_id": str(incident_id),
                    "created_by": actor.ref,
                    "trigger": trigger,
                }
            )
        )
        await service.commit()
    return _ephemeral(f"On it — {action}ing{f' *{focus}*' if focus else ''}…")


async def _handle_validate(
    args: list[str],
    *,
    channel_id: str,
    team_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """`@flare validate <claim>` — verify one claim against fresh evidence."""
    claim = " ".join(args).strip()
    if not claim:
        return _ephemeral(
            "Give me a claim to check, e.g. "
            "`@flare validate the checkout-api deploy caused the p99 spike`."
        )
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral(
                "No flare incident is tracking this channel. Try `@flare start`."
            )
        incident_id = incident.id
    await enqueue_claim_verification(
        {
            "incident_id": str(incident_id),
            "claim": claim,
            "created_by": slack_actor(user_id or "unknown").ref,
        }
    )
    return _ephemeral(f"Checking that claim against the evidence — *{claim}*…")


async def _handle_mode(
    args: list[str], *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, Any]:
    if not args or args[0] not in INCIDENT_MODES:
        return _ephemeral(f"mode must be one of: {', '.join(INCIDENT_MODES)}")
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        service = SteeringService(session, slack_actor(user_id or "unknown"))
        await service.set_mode(incident, args[0])
        await service.commit()
    return _ephemeral(f"Mode set to *{args[0]}*.")


async def _handle_status(
    args: list[str], *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, Any]:
    if not args or args[0].lower() not in INCIDENT_STATUSES:
        return _ephemeral(
            f"status must be one of: {', '.join(INCIDENT_STATUSES)}"
        )
    status = args[0].lower()
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        service = SteeringService(session, slack_actor(user_id or "unknown"))
        await service.set_status(incident, status)
        await service.commit()
    return _ephemeral(f"Status set to *{status}*.")


async def _handle_correct(
    args: list[str], *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, Any]:
    text = " ".join(args).strip().strip('"').strip("'")
    if not text:
        return _ephemeral('Usage: `@flare correct "what is actually true"`')
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        incident_id = incident.id
    await enqueue_correction(
        {"incident_id": str(incident_id), "text": text, "user_id": user_id}
    )
    return _ephemeral(
        ":pencil: Correction recorded — reconciling memory against it now."
    )

async def _handle_mitigation(
    *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, Any]:
    """`@flare mitigation` — options with Approve/Reject."""
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        return await mitigation_view(
            session,
            incident,
            actor=slack_actor(user_id or "unknown"),
            dashboard_url=_dashboard_url(incident.id),
        )


async def _handle_postmortem(
    *, channel_id: str, team_id: str, user_id: str | None
) -> dict[str, Any]:
    """`@flare postmortem` — generate/update the draft"""
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        incident_id = incident.id
    await enqueue_postmortem(
        {"incident_id": str(incident_id), "user_id": user_id}
    )
    return _ephemeral(
        ":memo: Writing the postmortem draft from memory — every claim links to "
        f"its evidence. It will appear at {_dashboard_url(incident_id)}"
    )


async def _handle_read(
    action: str, args: list[str], *, channel_id: str, team_id: str
) -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            return _ephemeral("No flare incident is tracking this channel.")
        url = _dashboard_url(incident.id)
        if action == "hypotheses":
            return await views.hypotheses_view(session, incident, url)
        if action == "evidence":
            return await views.evidence_view(
                session, incident, url, system=_flag_value(args, "--system")
            )
        if action == "questions":
            return await views.questions_view(session, incident, url)
        if action == "decisions":
            return await views.decisions_view(session, incident, url)
        if action == "brief":
            return await views.brief_view(session, incident, url)
        if action == "dashboard":
            return views.dashboard_view(url)
        return await _handle_timeline(session, incident, url)


def _flag_value(args: list[str], flag: str) -> str | None:
    if flag in args:
        index = args.index(flag)
        if index + 1 < len(args):
            return args[index + 1]
    return None


async def _handle_timeline(session: Any, incident: Incident, url: str) -> dict[str, Any]:
    rows = list(
        await session.scalars(
            select(TimelineEntry)
            .where(TimelineEntry.incident_id == incident.id)
            .order_by(TimelineEntry.occurred_at.desc().nullslast())
            .limit(_TIMELINE_N)
        )
    )
    if not rows:
        return _ephemeral(f"No timeline entries yet. Dashboard: {url}")
    lines = "\n".join(f"• [{_fmt_ts(r)}] {r.description}" for r in rows)
    return _ephemeral(f"*Latest timeline*\n{lines}\n\nFull dashboard: {url}")


def _fmt_ts(entry: TimelineEntry) -> str:
    """Best-effort UTC timestamp for a timeline entry."""
    ts = entry.occurred_at or entry.created_at
    if ts is None:
        return "unknown"
    return ts.strftime("%Y-%m-%d %H:%M UTC")
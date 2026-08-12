from __future__ import annotations

import logging
import uuid
from typing import Any

from flare.active.recovery import RecoveryWatcher, infer_service
from flare.active.scheduler import (
    owns_loop,
    resolve_interval,
    schedule_next_refresh,
    schedule_recovery_watch,
)
from flare.adaptive.governor import AntiSpamGovernor, MemoryDelta
from flare.adaptive.poster import GovernedPoster
from flare.adaptive.runner import leading_hypothesis, start_adaptive_run
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.investigation.graph import InvestigationPoster
from flare.models.core import ACTIVE_MODE, Incident
from flare.redis import get_redis
from flare.slack.posting import InvestigationSlackPoster, SlackPoster
from flare.tools.providers import resolve_default_service
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.pipeline.active")

_TERMINAL_STATUSES = frozenset({"resolved", "closed"})


async def _incident_state(
    incident_id: uuid.UUID,
) -> tuple[str, str | None, str] | None:
    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        if incident is None:
            return None
        return incident.mode, incident.slack_channel_id, incident.status


def _dashboard_url(incident_id: uuid.UUID) -> str:
    base = str(get_settings().dashboard_base_url).rstrip("/")
    return f"{base}/incidents/{incident_id}"


def _slack_poster(
    incident_id: uuid.UUID, channel: str | None, mode: str, *, force: bool = False
) -> InvestigationSlackPoster | None:
    if not channel:
        return None
    try:
        return InvestigationSlackPoster(
            SlackPoster(),
            channel=channel,
            incident_id=incident_id,
            mode=mode,
            force=force,
        )
    except Exception:
        _logger.warning("no Slack poster; running without channel posts")
        return None


async def _governed(
    incident_id: uuid.UUID, channel: str | None, mode: str
) -> InvestigationPoster | None:
    """A findings poster behind the governor, baselined on the current top."""
    inner = _slack_poster(incident_id, channel, mode)
    if inner is None:
        return None
    governor = AntiSpamGovernor(
        get_redis(),
        incident_id=incident_id,
        mode=mode,
        settings=get_settings().governor,
    )
    delta = MemoryDelta(previous_top=await leading_hypothesis(incident_id))
    return GovernedPoster(inner, governor, delta=delta)


async def active_refresh(ctx: dict, payload: dict[str, Any]) -> str:
    """One refresh: re-read telemetry, re-rank hypotheses, schedule the next."""
    incident_id = uuid.UUID(payload["incident_id"])
    token = str(payload.get("token", ""))
    tick = int(payload.get("tick", 1))
    manual = bool(payload.get("manual"))
    settings = get_settings()

    state = await _incident_state(incident_id)
    if state is None:
        return "no_incident"
    mode, channel, status = state
    if status in _TERMINAL_STATUSES:
        # The incident is resolved/closed — stop the loop and stop working.
        _logger.info("active loop stopping: incident is %s", status)
        return "stopped"
    if not manual:
        if mode != ACTIVE_MODE:
            _logger.info("active loop stopping: mode is %s", mode)
            return "stopped"
        if not await owns_loop(incident_id, token, redis=get_redis()):
            _logger.info("active loop stopping: token replaced or expired")
            return "superseded"

    # A manual `@flare refresh` is an explicit ask: answer in-channel regardless
    # of mode. The scheduled loop stays governed so active mode isn't chatty.
    poster = (
        _slack_poster(incident_id, channel, mode, force=True)
        if manual
        else await _governed(incident_id, channel, mode)
    )
    try:
        run_id = await start_adaptive_run(
            incident_id,
            trigger={
                "reason": "manual_refresh" if manual else "active_refresh",
                "tick": tick,
                "focus": "refresh telemetry and re-rank hypotheses",
                "signals": [],
                "messages": [],
            },
            created_by=(
                f"user:{payload['user_id']}"
                if manual and payload.get("user_id")
                else "scheduler"
            ),
            poster=poster,
            run_type="manual" if manual else "scheduled",
            agents=list(settings.active.agents),
            dashboard_url=_dashboard_url(incident_id),
        )
    except Exception:
        _logger.exception("active refresh tick %s failed", tick)
        run_id = None

    if manual:
        return str(run_id) if run_id else "degraded"

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, incident_id)
        interval = (
            await resolve_interval(session, incident)
            if incident is not None
            else int(payload.get("interval_s", settings.active.refresh_interval_s))
        )
    await schedule_next_refresh(
        incident_id,
        token=token,
        interval_s=interval,
        tick=tick,
        redis=get_redis(),
    )
    return str(run_id) if run_id else "degraded"


async def recovery_watch(ctx: dict, payload: dict[str, Any]) -> str:
    """One recovery poll after a mitigation; announce once, then stop."""
    incident_id = uuid.UUID(payload["incident_id"])
    attempt = int(payload.get("attempt", 1))
    settings = get_settings()

    state = await _incident_state(incident_id)
    if state is None:
        return "no_incident"
    mode, channel, status = state
    if status in _TERMINAL_STATUSES:
        _logger.info("recovery watch stopping: incident is %s", status)
        return "stopped"

    scenario = (
        settings.recovery.scenario
        or str(payload.get("scenario", DEFAULT_SCENARIO))
    )
    async with get_sessionmaker()() as session:
        service = payload.get("service") or await infer_service(
            session,
            incident_id,
            default=settings.recovery.default_service
            or resolve_default_service(scenario),
        )
    if not service:
        return "no_service"
    service = str(service)

    watcher = RecoveryWatcher(
        incident_id,
        sessionmaker=get_sessionmaker(),
        redis=get_redis(),
        settings=settings.recovery,
        service=service,
        scenario=scenario,
    )
    assessment = await watcher.poll()

    if assessment.recovered:
        result = await watcher.announce(
            assessment,
            mode=mode,
            governor=settings.governor,
            poster=_slack_poster(incident_id, channel, mode),
            dashboard_url=_dashboard_url(incident_id),
        )
        _logger.info(
            "recovery watch finished",
            extra={"incident_id": str(incident_id), "outcome": result.reason},
        )
        return "recovered" if result.recorded else result.reason

    if attempt >= settings.recovery.max_polls:
        _logger.info("recovery watch giving up after %s polls", attempt)
        return "gave_up"

    await schedule_recovery_watch(
        incident_id, attempt=attempt + 1, reason=str(payload.get("reason", "watch"))
    )
    return "waiting"
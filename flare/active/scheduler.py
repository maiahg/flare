from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flare.config import get_settings
from flare.models.core import Incident, IncidentSettings
from flare.redis import get_redis

_logger = logging.getLogger("flare.active.scheduler")

_ACTIVE_PREFIX = "flare:active:"
_RECOVERY_PREFIX = "flare:recovery:"

TOKEN_TTL_INTERVALS = 3

Enqueue = Callable[[dict[str, Any], int], Awaitable[None]]


def active_key(incident_id: uuid.UUID) -> str:
    return f"{_ACTIVE_PREFIX}{incident_id}"


def recovery_key(incident_id: uuid.UUID) -> str:
    """The key that makes the recovery post exactly-once (§9.1)."""
    return f"{_RECOVERY_PREFIX}announced:{incident_id}"


async def resolve_interval(session: AsyncSession, incident: Incident) -> int:
    """The refresh interval for this incident, clamped to the configured floor."""
    settings = get_settings().active
    row = await session.get(IncidentSettings, incident.id)
    configured = row.active_refresh_interval_s if row is not None else None
    interval = int(configured or settings.refresh_interval_s)
    return max(interval, settings.min_refresh_interval_s)


async def _default_enqueue(payload: dict[str, Any], defer_by: int) -> None:
    from flare.worker.enqueue import enqueue_active_refresh

    await enqueue_active_refresh(payload, defer_by=defer_by)


async def ensure_active_loop(
    incident_id: uuid.UUID,
    *,
    interval_s: int,
    redis: Redis | None = None,
    enqueue: Enqueue | None = None,
) -> str | None:
    """Start the refresh loop if one is not already running."""
    client = redis if redis is not None else get_redis()
    token = uuid.uuid4().hex
    claimed = await client.set(
        active_key(incident_id),
        token,
        nx=True,
        ex=interval_s * TOKEN_TTL_INTERVALS,
    )
    if not claimed:
        return None
    await (enqueue or _default_enqueue)(
        {
            "incident_id": str(incident_id),
            "token": token,
            "interval_s": interval_s,
            "tick": 1,
        },
        interval_s,
    )
    _logger.info(
        "active refresh loop started",
        extra={"incident_id": str(incident_id), "interval_s": interval_s},
    )
    return token


async def stop_active_loop(
    incident_id: uuid.UUID, *, redis: Redis | None = None
) -> None:
    """Drop the loop token. The next tick sees it gone and stops."""
    client = redis if redis is not None else get_redis()
    await client.delete(active_key(incident_id))


async def loop_token(
    incident_id: uuid.UUID, *, redis: Redis | None = None
) -> str | None:
    client = redis if redis is not None else get_redis()
    raw = await client.get(active_key(incident_id))
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def owns_loop(
    incident_id: uuid.UUID, token: str, *, redis: Redis | None = None
) -> bool:
    """True if ``token`` is still the incident's live loop."""
    return await loop_token(incident_id, redis=redis) == token


async def schedule_next_refresh(
    incident_id: uuid.UUID,
    *,
    token: str,
    interval_s: int,
    tick: int,
    redis: Redis | None = None,
    enqueue: Enqueue | None = None,
) -> bool:
    """Queue the next tick and renew the token. False if the loop was stopped."""
    client = redis if redis is not None else get_redis()
    if not await owns_loop(incident_id, token, redis=client):
        return False
    await client.expire(active_key(incident_id), interval_s * TOKEN_TTL_INTERVALS)
    await (enqueue or _default_enqueue)(
        {
            "incident_id": str(incident_id),
            "token": token,
            "interval_s": interval_s,
            "tick": tick + 1,
        },
        interval_s,
    )
    return True


async def _default_recovery_enqueue(payload: dict[str, Any], defer_by: int) -> None:
    from flare.worker.enqueue import enqueue_recovery_watch

    await enqueue_recovery_watch(payload, defer_by=defer_by)


async def schedule_recovery_watch(
    incident_id: uuid.UUID,
    *,
    attempt: int = 1,
    defer_by: int | None = None,
    reason: str = "mitigation approved",
    enqueue: Enqueue | None = None,
) -> None:
    """Ask the worker to watch for recovery after a mitigation"""
    settings = get_settings().recovery
    await (enqueue or _default_recovery_enqueue)(
        {
            "incident_id": str(incident_id),
            "attempt": attempt,
            "reason": reason,
        },
        settings.poll_interval_s if defer_by is None else defer_by,
    )


__all__ = [
    "TOKEN_TTL_INTERVALS",
    "active_key",
    "ensure_active_loop",
    "loop_token",
    "owns_loop",
    "recovery_key",
    "resolve_interval",
    "schedule_next_refresh",
    "schedule_recovery_watch",
    "stop_active_loop",
]
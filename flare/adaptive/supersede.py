from __future__ import annotations

import uuid

from redis.asyncio import Redis

_INFLIGHT_PREFIX = "flare:inflight:"
_CANCEL_PREFIX = "flare:cancel:"

#: Safety valve: an in-flight marker outlives any sane run but not the incident.
DEFAULT_INFLIGHT_TTL_S = 15 * 60
DEFAULT_CANCEL_TTL_S = 15 * 60


def inflight_key(incident_id: uuid.UUID) -> str:
    return f"{_INFLIGHT_PREFIX}{incident_id}"


def cancel_key(run_id: uuid.UUID) -> str:
    return f"{_CANCEL_PREFIX}{run_id}"


async def register_run(
    redis: Redis,
    incident_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    ttl_s: int = DEFAULT_INFLIGHT_TTL_S,
) -> None:
    """Mark ``run_id`` as the incident's in-flight run."""
    await redis.set(inflight_key(incident_id), str(run_id), ex=ttl_s)


async def current_run(redis: Redis, incident_id: uuid.UUID) -> uuid.UUID | None:
    """The run currently executing for this incident, if any."""
    raw = await redis.get(inflight_key(incident_id))
    if raw is None:
        return None
    try:
        return uuid.UUID(raw.decode() if isinstance(raw, bytes) else str(raw))
    except ValueError:  # pragma: no cover - defensive
        return None


async def clear_run(redis: Redis, incident_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Release the in-flight marker, but only if we still own it."""
    holder = await current_run(redis, incident_id)
    if holder == run_id:
        await redis.delete(inflight_key(incident_id))


async def request_supersede(
    redis: Redis,
    incident_id: uuid.UUID,
    *,
    ttl_s: int = DEFAULT_CANCEL_TTL_S,
) -> uuid.UUID | None:
    """Tombstone the in-flight run (if any) and return its id."""
    run_id = await current_run(redis, incident_id)
    if run_id is None:
        return None
    await redis.set(cancel_key(run_id), "1", ex=ttl_s)
    return run_id


async def is_superseded(redis: Redis, run_id: uuid.UUID) -> bool:
    """Has this run been tombstoned? Polled at every graph checkpoint."""
    return bool(await redis.exists(cancel_key(run_id)))


async def clear_supersede(redis: Redis, run_id: uuid.UUID) -> None:
    await redis.delete(cancel_key(run_id))

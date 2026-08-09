from __future__ import annotations

from redis.asyncio import Redis

DEFAULT_TTL_SECONDS = 60 * 5
KEY_PREFIX = "slack:event:"


async def mark_seen(
    redis: Redis,
    event_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    prefix: str = KEY_PREFIX,
) -> bool:
    key = f"{prefix}{event_id}"
    was_set = await redis.set(key, "1", nx=True, ex=ttl_seconds)
    return not was_set
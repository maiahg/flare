from __future__ import annotations

from redis.asyncio import Redis

from flare.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client, creating it on first use."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def reset_redis() -> None:
    """Close the client and clear the cache so the next call rebuilds it."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
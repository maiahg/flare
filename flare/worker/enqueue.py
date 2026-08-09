from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from flare.config import get_settings

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(str(get_settings().redis_url)))
    return _pool


async def enqueue_message(payload: dict[str, Any]) -> None:
    """Enqueue a normalized Slack message for the scribe pipeline."""
    pool = await get_arq_pool()
    await pool.enqueue_job("process_message", payload)


async def enqueue_initial_run(payload: dict[str, Any]) -> None:
    """Enqueue an initial investigation run (off the Slack request path)."""
    pool = await get_arq_pool()
    await pool.enqueue_job("run_initial_investigation", payload)
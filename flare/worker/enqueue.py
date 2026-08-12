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


async def enqueue_comms_draft(payload: dict[str, Any]) -> None:
    """Generate a comms draft off the Slack request path"""
    pool = await get_arq_pool()
    await pool.enqueue_job("generate_comms_draft", payload)


async def enqueue_active_refresh(payload: dict[str, Any], *, defer_by: int = 0) -> None:
    """Schedule the next active-mode refresh tick."""
    pool = await get_arq_pool()
    await pool.enqueue_job("active_refresh", payload, _defer_by=defer_by or None)


async def enqueue_recovery_watch(payload: dict[str, Any], *, defer_by: int = 0) -> None:
    """Schedule a post-mitigation recovery poll (read-only)."""
    pool = await get_arq_pool()
    await pool.enqueue_job("recovery_watch", payload, _defer_by=defer_by or None)


async def enqueue_postmortem(payload: dict[str, Any]) -> None:
    """Generate a postmortem draft on the worker. """
    pool = await get_arq_pool()
    await pool.enqueue_job("generate_postmortem_draft", payload)


async def enqueue_correction(payload: dict[str, Any]) -> None:
    """Reconcile a human correction off the Slack request path (LLM work)."""
    pool = await get_arq_pool()
    await pool.enqueue_job("reconcile_correction", payload)


async def enqueue_mention(payload: dict[str, Any]) -> None:
    """Answer an `@flare` mention publicly, off the Slack events ack path."""
    pool = await get_arq_pool()
    await pool.enqueue_job("handle_mention_job", payload)


async def enqueue_adaptive_run(payload: dict[str, Any], *, defer_by: int = 0) -> None:
    """Schedule the coalesced adaptive run ``defer_by`` seconds out"""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_adaptive_investigation", payload, _defer_by=defer_by or None
    )


async def enqueue_claim_verification(payload: dict[str, Any]) -> None:
    """Verify a claim against fresh evidence off the Slack request path."""
    pool = await get_arq_pool()
    await pool.enqueue_job("run_claim_verification", payload)
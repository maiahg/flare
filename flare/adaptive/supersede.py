from __future__ import annotations

import json
import uuid
from typing import Any

from redis.asyncio import Redis

_PREFIX = "flare:coalesce:"


def pending_key(incident_id: uuid.UUID) -> str:
    return f"{_PREFIX}{incident_id}:pending"


def window_key(incident_id: uuid.UUID) -> str:
    return f"{_PREFIX}{incident_id}:window"


async def add_pending(
    redis: Redis,
    incident_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    ttl_s: int,
) -> None:
    """Queue one message's context for the next run, without opening a window."""
    key = pending_key(incident_id)
    pipe = redis.pipeline()
    pipe.rpush(key, json.dumps(payload, default=str))
    pipe.expire(key, ttl_s)
    await pipe.execute()


async def open_window(redis: Redis, incident_id: uuid.UUID, *, window_s: int) -> bool:
    """Try to open the coalesce window. ``True`` means *you* must schedule the run."""
    was_set = await redis.set(window_key(incident_id), "1", nx=True, ex=window_s)
    return bool(was_set)


async def drain(
    redis: Redis, incident_id: uuid.UUID, *, limit: int
) -> list[dict[str, Any]]:
    """Take everything queued for this incident and close the window."""
    pipe = redis.pipeline()
    pipe.lrange(pending_key(incident_id), 0, -1)
    pipe.delete(pending_key(incident_id))
    pipe.delete(window_key(incident_id))
    raw, *_ = await pipe.execute()

    items: list[dict[str, Any]] = []
    for entry in raw[-limit:] if limit else raw:
        try:
            decoded = json.loads(entry)
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, dict):
            items.append(decoded)
    return items


def merge_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold coalesced message payloads into one trigger context."""
    messages: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    reasons: list[str] = []

    for item in items:
        messages.append(
            {
                "slack_ts": item.get("slack_ts"),
                "user_id": item.get("user_id"),
                "text": item.get("text", ""),
            }
        )
        reasons.extend(item.get("reasons", []))
        for signal in item.get("signals", []):
            key = (str(signal.get("type", "")), str(signal.get("text", "")))
            if key in seen:
                continue
            seen.add(key)
            signals.append(signal)

    return {
        "reason": "adaptive",
        "messages": messages,
        "signals": signals,
        "reasons": reasons[:20],
        "coalesced": len(items),
    }
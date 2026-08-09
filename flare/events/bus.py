from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from flare.redis import get_redis

EVENT_RUN_STARTED = "run.started"
EVENT_RUN_PROGRESS = "run.progress"
EVENT_RUN_FINISHED = "run.finished"
EVENT_MEMORY_UPDATED = "memory.updated"
EVENT_SUMMARY_UPDATED = "summary.updated"
EVENT_APPROVAL_REQUESTED = "approval.requested"
EVENT_SLACK_POSTED = "slack.posted"

EVENT_NAMES = (
    EVENT_RUN_STARTED,
    EVENT_RUN_PROGRESS,
    EVENT_RUN_FINISHED,
    EVENT_MEMORY_UPDATED,
    EVENT_SUMMARY_UPDATED,
    EVENT_APPROVAL_REQUESTED,
    EVENT_SLACK_POSTED,
)

_CHANNEL_PREFIX = "flare:incident:"


def channel_for(incident_id: uuid.UUID) -> str:
    """The pub/sub channel carrying one incident's events."""
    return f"{_CHANNEL_PREFIX}{incident_id}"


class Event(BaseModel):
    """A realtime notification about an incident."""

    event: str
    incident_id: uuid.UUID
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


async def publish(event: Event) -> int:
    """Publish an event. Returns the number of subscribers that received it."""
    redis = get_redis()
    return int(
        await redis.publish(channel_for(event.incident_id), event.model_dump_json())
    )


@asynccontextmanager
async def subscribe(incident_id: uuid.UUID) -> AsyncIterator[AsyncIterator[Event]]:
    """Subscribe to one incident's events for the duration of the context."""
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_for(incident_id))

    async def iterator() -> AsyncIterator[Event]:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue  # subscribe/unsubscribe confirmations
            payload = message["data"]
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            yield Event.model_validate_json(payload)

    try:
        yield iterator()
    finally:
        await pubsub.unsubscribe(channel_for(incident_id))
        await pubsub.aclose()
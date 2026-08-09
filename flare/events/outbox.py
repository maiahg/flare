from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from flare.events.bus import Event, publish

#: Key under which pending events hang off ``session.info``.
PENDING_KEY = "flare.events.pending"

_logger = logging.getLogger("flare.events")


def enqueue(session: AsyncSession, event: Event) -> None:
    """Queue an event to publish once the current transaction commits."""
    session.info.setdefault(PENDING_KEY, []).append(event)


def pending(session: AsyncSession) -> list[Event]:
    """The events queued so far (used by tests and diagnostics)."""
    events: list[Event] = session.info.get(PENDING_KEY, [])
    return list(events)


def discard(session: AsyncSession) -> None:
    """Drop queued events — call after a rollback."""
    session.info.pop(PENDING_KEY, None)


async def publish_pending(session: AsyncSession) -> int:
    """Publish and clear the queue. Returns how many events were published."""
    events: list[Event] = session.info.pop(PENDING_KEY, [])
    published = 0
    for event in events:
        try:
            await publish(event)
            published += 1
        except Exception:
            _logger.warning(
                "failed to publish %s for incident %s",
                event.event,
                event.incident_id,
                exc_info=True,
            )
    return published


async def commit_and_publish(session: AsyncSession) -> int:
    """Commit, then publish the events that commit made real."""
    await session.commit()
    return await publish_pending(session)
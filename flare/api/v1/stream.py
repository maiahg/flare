from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from flare.api.v1.incidents import IncidentDep
from flare.events.bus import Event, subscribe

router = APIRouter(tags=["stream"])

_logger = logging.getLogger("flare.stream")

#: Events buffered per connection before the oldest is dropped.
QUEUE_MAXSIZE = 100

#: Seconds of silence before a keepalive comment is sent.
HEARTBEAT_SECONDS = 15.0


def format_sse(event: Event) -> str:
    """Render an event as an SSE frame."""
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


async def _relay(incident_id: uuid.UUID, queue: asyncio.Queue[Event]) -> None:
    """Pump bus events into the bounded queue, dropping oldest on overflow."""
    async with subscribe(incident_id) as events:
        async for event in events:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # drop oldest
                _logger.warning(
                    "SSE consumer for incident %s is slow; dropped an event",
                    incident_id,
                )
            queue.put_nowait(event)


async def event_stream(incident_id: uuid.UUID) -> AsyncIterator[str]:
    """Yield SSE frames for an incident until the client goes away."""
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    relay = asyncio.create_task(_relay(incident_id, queue))
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield format_sse(event)
    finally:
        relay.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay


@router.get(
    "/incidents/{incident_id}/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Live incident events (§4.4).",
        }
    },
)
async def stream_incident(incident: IncidentDep) -> StreamingResponse:
    """Subscribe to an incident's live event feed."""
    return StreamingResponse(
        event_stream(incident.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
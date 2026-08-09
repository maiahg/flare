from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

class InternalEvent(BaseModel):
    """A normalized inbound Slack event — the gateway's canonical shape."""

    model_config = ConfigDict(frozen=True)

    team_id: str
    event_id: str
    event_type: str
    channel: str | None = None
    user: str | None = None
    text: str | None = None
    ts: str | None = None
    event_time: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


def is_bot_message(event: dict[str, Any]) -> bool:
    return bool(event.get("bot_id")) or event.get("subtype") == "bot_message"


def normalize_event_callback(payload: dict[str, Any]) -> InternalEvent:
    """Build an :class:`InternalEvent` from an ``event_callback`` payload."""
    event: dict[str, Any] = payload.get("event", {}) or {}
    return InternalEvent(
        team_id=payload.get("team_id", ""),
        event_id=payload.get("event_id", ""),
        event_type=event.get("type", ""),
        channel=event.get("channel"),
        user=event.get("user"),
        text=event.get("text"),
        ts=event.get("ts"),
        event_time=payload.get("event_time"),
        raw=payload,
    )
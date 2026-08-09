from __future__ import annotations

from dataclasses import dataclass

from flare.memory.authority import human_actor


@dataclass(frozen=True)
class Actor:
    """A human steering the incident."""

    user_id: str
    surface: str = "api"
    display_name: str | None = None

    @property
    def ref(self) -> str:
        """The ``memory_revisions.actor`` value: ``user:<user_id>``."""
        return human_actor(self.user_id)

    def reason(self, action: str) -> str:
        """A short human-readable audit reason for a revision."""
        who = self.display_name or self.user_id
        return f"{action} by {who} via {self.surface}"


def slack_actor(user_id: str, display_name: str | None = None) -> Actor:
    """An actor for a Slack interaction / slash command."""
    return Actor(user_id=user_id, surface="slack", display_name=display_name)
from __future__ import annotations

_PROACTIVE_MODES = frozenset({"assist", "active"})


def can_post_proactively(mode: str) -> bool:
    """True only in modes where the bot may post without being asked."""
    return mode in _PROACTIVE_MODES
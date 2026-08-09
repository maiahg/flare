from __future__ import annotations

import logging
from dataclasses import replace

from flare.adaptive.governor import AntiSpamGovernor, MemoryDelta
from flare.slack.posting import InvestigationSlackPoster

_logger = logging.getLogger("flare.adaptive.poster")


class GovernedPoster:
    """Wraps :class:`InvestigationSlackPoster` with the anti-spam gates."""

    def __init__(
        self,
        inner: InvestigationSlackPoster,
        governor: AntiSpamGovernor,
        *,
        delta: MemoryDelta | None = None,
    ) -> None:
        self._inner = inner
        self._governor = governor
        self._delta = delta
        #: Populated as posts are judged, so the run trace can explain silence.
        self.decisions: list[str] = []

    def set_delta(self, delta: MemoryDelta) -> None:
        """Update the memory delta the materiality bar is judged against."""
        self._delta = delta

    async def post_intent(self, checking: list[str]) -> None:
        text = f"Checking {', '.join(checking)}"
        decision = await self._governor.allow("intent", text)
        self.decisions.append(f"intent: {decision.reason}")
        if decision.allowed:
            await self._inner.post_intent(checking)

    async def post_findings(
        self, *, summary: str | None, top_hypothesis: str | None, dashboard_url: str
    ) -> None:
        text = " ".join(filter(None, (summary, top_hypothesis)))
        delta = self._delta
        if delta is not None and delta.current_top is None:
            delta = replace(delta, current_top=top_hypothesis)
        decision = await self._governor.allow("findings", text, delta=delta)
        self.decisions.append(f"findings: {decision.reason}")
        if decision.allowed:
            await self._inner.post_findings(
                summary=summary,
                top_hypothesis=top_hypothesis,
                dashboard_url=dashboard_url,
            )
            return
        if decision.nudge:
            await self._inner.post_raw(decision.nudge)
        _logger.info(
            "findings post suppressed", extra={"reason": decision.reason}
        )
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis

from flare.config import GovernorSettings
from flare.slack.posting import can_post_proactively

_BUDGET_PREFIX = "flare:postbudget:"
_RECENT_PREFIX = "flare:postrecent:"
_OVERFLOW_PREFIX = "flare:postoverflow:"
_NUDGED_PREFIX = "flare:postnudged:"

_WORD = re.compile(r"[a-z0-9]+")

#: Intent ("checking metrics, deploys…") is chatter unless the incident is
#: in active mode — it tells the channel nothing it can act on.
_ACTIVE_ONLY_KINDS = frozenset({"intent"})


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _fingerprint(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:32]


def _similarity(a: str, b: str) -> float:
    """Jaccard over content words — cheap near-duplicate detection."""
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


@dataclass(frozen=True)
class PostDecision:
    """Why a post was allowed or suppressed — surfaced in logs and traces."""

    allowed: bool
    reason: str
    #: Set when the budget just ran out: post this instead, once per window.
    nudge: str | None = None


@dataclass
class MemoryDelta:
    """What actually changed, for the materiality bar."""

    new_hypotheses: int = 0
    rejected_hypotheses: int = 0
    #: The leading hypothesis before/after this run.
    previous_top: str | None = None
    current_top: str | None = None
    impact_changed: bool = False
    recovery_state_changed: bool = False
    new_evidence: int = 0
    notes: list[str] = field(default_factory=list)

    def materiality(self) -> tuple[bool, str]:
        """Is this worth interrupting a channel of humans mid-incident?"""
        if self.recovery_state_changed:
            return True, "recovery state changed"
        if self.impact_changed:
            return True, "confirmed impact changed"
        if self.previous_top != self.current_top and self.current_top:
            return True, "leading hypothesis changed"
        if self.rejected_hypotheses:
            return True, f"{self.rejected_hypotheses} hypothesis rejected"
        if self.new_hypotheses:
            return True, f"{self.new_hypotheses} new hypothesis"
        if self.new_evidence:
            return False, f"only new evidence ({self.new_evidence}) — dashboard only"
        return False, "no material change"


class AntiSpamGovernor:
    """The single gate every proactive post passes through."""

    def __init__(
        self,
        redis: Redis,
        *,
        incident_id: uuid.UUID,
        mode: str,
        settings: GovernorSettings,
    ) -> None:
        self._redis = redis
        self._incident_id = incident_id
        self._mode = mode
        self._settings = settings

    # -- gate 3: dedup ----------------------------------------------------
    async def _is_duplicate(self, text: str) -> bool:
        key = f"{_RECENT_PREFIX}{self._incident_id}"
        recent: list[Any] = await self._redis.lrange(  # type: ignore[misc]
            key, 0, self._settings.dedup_history - 1
        )
        fingerprint = _fingerprint(text)
        normalized = _normalize(text)
        for entry in recent:
            decoded = entry.decode() if isinstance(entry, bytes) else str(entry)
            stored_fp, _, stored_text = decoded.partition("|")
            if stored_fp == fingerprint:
                return True
            if _similarity(normalized, stored_text) >= self._settings.dedup_similarity:
                return True
        return False

    async def _remember(self, text: str) -> None:
        key = f"{_RECENT_PREFIX}{self._incident_id}"
        pipe = self._redis.pipeline()
        pipe.lpush(key, f"{_fingerprint(text)}|{_normalize(text)}")
        pipe.ltrim(key, 0, self._settings.dedup_history - 1)
        pipe.expire(key, self._settings.dedup_ttl_s)
        await pipe.execute()

    # -- gate 4: budget ---------------------------------------------------
    async def _consume_budget(self) -> bool:
        """Token bucket per (incident, mode). ``False`` means over budget."""
        key = f"{_BUDGET_PREFIX}{self._incident_id}:{self._mode}"
        used = int(await self._redis.incr(key))
        if used == 1:
            await self._redis.expire(key, self._settings.post_window_s)
        return used <= self._settings.post_budget

    async def _overflow_nudge(self) -> str | None:
        """One "N updates in the dashboard" line per budget window."""
        overflow_key = f"{_OVERFLOW_PREFIX}{self._incident_id}"
        nudged_key = f"{_NUDGED_PREFIX}{self._incident_id}"
        count = int(await self._redis.incr(overflow_key))
        if count == 1:
            await self._redis.expire(overflow_key, self._settings.post_window_s)
        first = await self._redis.set(
            nudged_key, "1", nx=True, ex=self._settings.post_window_s
        )
        if not first:
            return None
        return f":bar_chart: {count} update(s) waiting in the dashboard."

    async def allow(
        self, kind: str, text: str, *, delta: MemoryDelta | None = None
    ) -> PostDecision:
        """Run all gates for one candidate post."""
        # 1) mode
        if not can_post_proactively(self._mode):
            return PostDecision(False, f"mode {self._mode} suppresses proactive posts")
        if kind in _ACTIVE_ONLY_KINDS and self._mode != "active":
            return PostDecision(False, f"{kind} posts are active-mode only")

        # 2) materiality. ``delta is None`` means the caller has no delta to
        #    judge (e.g. the initial run's findings, which *are* the point of
        #    the run) and skips the bar rather than failing it.
        if delta is not None:
            material, why = delta.materiality()
            if not material:
                return PostDecision(False, f"not material: {why}")

        # 3) dedup
        if await self._is_duplicate(text):
            return PostDecision(False, "near-duplicate of a recent post")

        # 4) budget
        if not await self._consume_budget():
            return PostDecision(
                False, "post budget exhausted", nudge=await self._overflow_nudge()
            )

        await self._remember(text)
        return PostDecision(True, "allowed")
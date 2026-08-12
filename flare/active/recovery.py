from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flare.adaptive.governor import AntiSpamGovernor, MemoryDelta
from flare.config import GovernorSettings, RecoverySettings
from flare.investigation.recorder import RunRecorder
from flare.memory import MemoryRepository
from flare.memory.spec import entity_type
from flare.models.claims import TimelineEntry
from flare.models.core import Incident
from flare.models.tracing import InvestigationRun
from flare.events.outbox import commit_and_publish
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.active.recovery")

WATCHER_NAME = "RecoveryWatcher"

RECOVERED_STATUS = "monitoring"
_RECOVERABLE_STATUSES = ("open", "mitigating")


@dataclass(frozen=True)
class RecoveryAssessment:
    """Whether the metric came back, and the numbers that say so."""

    recovered: bool
    reason: str
    service: str
    metric: str
    baseline: float | None = None
    peak: float | None = None
    latest: float | None = None
    tool_call_id: uuid.UUID | None = None
    limitations: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.baseline is None or self.latest is None:
            return f"{self.metric} on {self.service}: {self.reason}"
        return (
            f"{self.metric} on {self.service} is back to {self.latest:g} "
            f"(peak {self.peak:g}, pre-incident {self.baseline:g})"
        )


@dataclass(frozen=True)
class AnnouncementResult:
    """What announcing did: recorded once, posted at most once."""

    recorded: bool
    posted: bool
    reason: str


def assess(
    series: Mapping[str, Any],
    *,
    service: str,
    metric: str,
    settings: RecoverySettings,
    limitations: list[str] | None = None,
) -> RecoveryAssessment:
    """Decide recovery from a metric series. Deterministic, and conservative."""
    notes = list(limitations or [])
    values = [float(v) for v in series.values() if isinstance(v, int | float)]

    def verdict(
        recovered: bool,
        reason: str,
        *,
        baseline: float | None = None,
        peak: float | None = None,
        latest: float | None = None,
    ) -> RecoveryAssessment:
        return RecoveryAssessment(
            recovered=recovered,
            reason=reason,
            service=service,
            metric=metric,
            baseline=baseline,
            peak=peak,
            latest=latest,
            limitations=notes,
        )

    if len(values) < 2:
        return verdict(False, "not enough samples to judge recovery")

    baseline, latest, peak = values[0], values[-1], max(values)
    seen = {"baseline": baseline, "peak": peak, "latest": latest}
    if baseline <= 0:
        return verdict(False, "no usable pre-incident baseline", **seen)
    if peak < baseline * settings.degraded_ratio:
        return verdict(False, "no degradation visible in this window", **seen)
    if latest <= baseline * settings.recovered_ratio:
        return verdict(True, "metric returned to its pre-incident level", **seen)
    return verdict(False, "metric is still elevated", **seen)


class RecoveryWatcher:
    """One poll of one incident's health, plus the single state-change post."""

    def __init__(
        self,
        incident_id: uuid.UUID,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: RecoverySettings,
        service: str,
        scenario: str = DEFAULT_SCENARIO,
    ) -> None:
        self._incident_id = incident_id
        self._sm = sessionmaker
        self._redis = redis
        self._settings = settings
        self._service = service
        self._scenario = scenario
        self.run_id: uuid.UUID | None = None

    async def poll(self) -> RecoveryAssessment:
        """Read the metric through the broker, audited as a ``recovery`` run."""
        recorder = RunRecorder(
            self._sm,
            incident_id=self._incident_id,
            run_type="recovery",
            trigger={"reason": "recovery_watch", "service": self._service},
            created_by=WATCHER_NAME,
            scenario=self._scenario,
        )
        self.run_id = await recorder.start()
        async with recorder.agent_step(WATCHER_NAME, 0) as step:
            brokered = await step.broker.call(
                "metrics.query",
                service=self._service,
                metric=self._settings.metric,
                window_minutes=self._settings.window_minutes,
            )
            data = brokered.result.data or {}
            assessment = assess(
                data.get("series") or {},
                service=self._service,
                metric=self._settings.metric,
                settings=self._settings,
                limitations=list(brokered.result.limitations),
            )
            assessment = replace(assessment, tool_call_id=brokered.tool_call_id)
            step.output = {
                "recovered": assessment.recovered,
                "reason": assessment.reason,
            }
        await recorder.finish(
            status="done",
            limitations=assessment.limitations,
            summary=assessment.describe(),
        )
        return assessment

    async def announce(
        self,
        assessment: RecoveryAssessment,
        *,
        mode: str,
        governor: GovernorSettings,
        poster: Any | None = None,
        dashboard_url: str = "",
    ) -> AnnouncementResult:
        """Record the state change once, and post it at most once."""
        if not assessment.recovered:
            return AnnouncementResult(False, False, "not recovered")

        claimed = await self._redis.set(
            _announced_key(self._incident_id), "1", nx=True
        )
        if not claimed:
            return AnnouncementResult(False, False, "already announced")

        await self._record(assessment)

        text = (
            f":white_check_mark: *Recovery* — {assessment.describe()}. "
            "Still monitoring."
        )
        if dashboard_url:
            text += f" <{dashboard_url}|Incident →>"

        gov = AntiSpamGovernor(
            self._redis,
            incident_id=self._incident_id,
            mode=mode,
            settings=governor,
        )
        decision = await gov.allow(
            "recovery", text, delta=MemoryDelta(recovery_state_changed=True)
        )
        if decision.allowed and poster is not None:
            await poster.post_raw(text)
            return AnnouncementResult(True, True, "posted")
        _logger.info(
            "recovery recorded without a post",
            extra={"incident_id": str(self._incident_id), "reason": decision.reason},
        )
        return AnnouncementResult(True, False, decision.reason)

    async def _record(self, assessment: RecoveryAssessment) -> None:
        """Journal the recovery: a cited timeline entry + the incident status."""
        async with self._sm() as session:
            repo = MemoryRepository(session, run_id=self.run_id)
            await repo.create(
                TimelineEntry,
                incident_id=self._incident_id,
                kind="fact",
                confidence=0.9,
                source={
                    "type": "metrics",
                    "tool_call_id": (
                        str(assessment.tool_call_id)
                        if assessment.tool_call_id
                        else None
                    ),
                    "run_id": str(self.run_id) if self.run_id else None,
                    "service": assessment.service,
                    "metric": assessment.metric,
                },
                created_by=WATCHER_NAME,
                reason="observed recovery after a mitigation",
                entry_type="observation",
                occurred_at=datetime.now(UTC),
                description=f"Recovery observed: {assessment.describe()}",
            )

            incident = await session.get(Incident, self._incident_id)
            if incident is not None and incident.status in _RECOVERABLE_STATUSES:
                before = {"status": incident.status}
                incident.status = RECOVERED_STATUS
                await session.flush()
                await repo.record_change(
                    entity_type_name=entity_type(Incident),
                    entity_id=incident.id,
                    incident_id=incident.id,
                    op="update",
                    before=before,
                    after={"status": RECOVERED_STATUS},
                    actor=WATCHER_NAME,
                    reason="metric returned to its pre-incident level",
                )
            await commit_and_publish(session)


def _announced_key(incident_id: uuid.UUID) -> str:
    from flare.active.scheduler import recovery_key

    return recovery_key(incident_id)


async def infer_service(
    session: AsyncSession, incident_id: uuid.UUID, *, default: str | None = None
) -> str | None:
    """Which service to watch: whatever the last run was actually looking at."""
    stored = await session.scalar(
        select(InvestigationRun.plan)
        .where(
            InvestigationRun.incident_id == incident_id,
            InvestigationRun.plan.isnot(None),
        )
        .order_by(InvestigationRun.created_at.desc())
        .limit(1)
    )
    plan = dict(stored or {})
    for key in ("service", "suspect_service"):
        value = plan.get(key)
        if isinstance(value, str) and value:
            return value
    return default


__all__ = [
    "RECOVERED_STATUS",
    "WATCHER_NAME",
    "AnnouncementResult",
    "RecoveryAssessment",
    "RecoveryWatcher",
    "assess",
    "infer_service",
]
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.agents.comms import (
    CommsAgent,
    CommsContext,
    UnknownAudienceError,
    clean_body,
    fallback_body,
)
from flare.events.outbox import commit_and_publish
from flare.llm import LLMClient
from flare.memory import MemoryRepository
from flare.models.claims import (
    COMMS_AUDIENCES,
    CommsDraft,
    Fact,
    Hypothesis,
    MitigationOption,
    Summary,
)
from flare.models.core import Incident
from flare.models.provenance import HUMAN_STATEMENT_KIND, INFERENCE_KIND
from flare.steering.actors import Actor
from flare.steering.errors import NotFoundError, ValidationError

_logger = logging.getLogger("flare.comms")

CONTEXT_LIMIT = 8

AGENT_DRAFT_CONFIDENCE = 0.6
HUMAN_DRAFT_CONFIDENCE = 1.0

@dataclass(frozen=True)
class DraftResult:
    """A draft plus how it came to be, for the caller's confirmation text."""

    draft: CommsDraft
    generated: bool
    degraded: bool = False


class CommsService:
    """Journaled, versioned writes to ``comms_drafts``. Cannot send anything."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        *,
        llm: LLMClient | None = None,
        model: str | None = None,
    ) -> None:
        self._session = session
        self._actor = actor
        self._llm = llm
        self._model = model
        self._repo = MemoryRepository(session)
        self._after_commit: list[Callable[[], Awaitable[None]]] = []

    # ---- transaction boundary --------------------------------------------

    def defer(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._after_commit.append(hook)

    async def commit(self, *refresh: object) -> None:
        await commit_and_publish(self._session)
        for entity in refresh:
            if entity is not None:
                await self._session.refresh(entity)
        hooks, self._after_commit = self._after_commit, []
        for hook in hooks:
            await hook()

    # ---- reads ------------------------------------------------------------

    async def latest(self, incident: Incident, audience: str) -> CommsDraft | None:
        """The current draft for an audience (highest version wins)."""
        _validate_audience(audience)
        return await self._session.scalar(
            select(CommsDraft)
            .where(
                CommsDraft.incident_id == incident.id,
                CommsDraft.audience == audience,
            )
            .order_by(CommsDraft.version.desc())
            .limit(1)
        )

    # ---- writes -----------------------------------------------------------

    async def generate(self, incident: Incident, *, audience: str) -> DraftResult:
        """Write a fresh version for ``audience`` from current memory."""
        _validate_audience(audience)
        context = await self.context(incident)

        degraded = False
        body = ""
        if self._llm is not None:
            agent = CommsAgent(self._llm, model=self._model)
            try:
                body = await agent.run(audience=audience, context=context)
            except UnknownAudienceError:
                raise
            except Exception: 
                _logger.warning("comms generation failed; using fallback body",
                                exc_info=True)
                degraded = True
        if not body:
            degraded = degraded or self._llm is None
            body = fallback_body(audience, context)

        draft = await self._new_version(
            incident,
            audience=audience,
            body=body,
            created_by=CommsAgent.agent_name,
            kind=INFERENCE_KIND,
            confidence=AGENT_DRAFT_CONFIDENCE,
            source={
                "type": "comms",
                "audience": audience,
                "generated_by": CommsAgent.agent_name,
                "requested_by": self._actor.ref,
                "degraded": degraded,
                "grounded_in": context.provenance,
            },
            reason="generated a comms draft",
        )
        return DraftResult(draft=draft, generated=True, degraded=degraded)

    async def revise(
        self, incident: Incident, *, body: str, edited_from: uuid.UUID
    ) -> DraftResult:
        """Store a human's edit as the next version."""
        text = clean_body(body)
        if not text:
            raise ValidationError("a comms draft cannot be empty")

        previous = await self._scoped(incident, edited_from)
        audience = previous.audience or "internal"
        _validate_audience(audience)
        if clean_body(previous.body or "") == text:
            return DraftResult(draft=previous, generated=False)

        draft = await self._new_version(
            incident,
            audience=audience,
            body=text,
            created_by=self._actor.ref,
            kind=HUMAN_STATEMENT_KIND,
            confidence=HUMAN_DRAFT_CONFIDENCE,
            source={
                "type": "human",
                "surface": self._actor.surface,
                "user_id": self._actor.user_id,
                "audience": audience,
                "edited_from": str(edited_from),
            },
            reason="edited a comms draft",
        )
        return DraftResult(draft=draft, generated=False)

    async def _new_version(
        self,
        incident: Incident,
        *,
        audience: str,
        body: str,
        created_by: str,
        kind: str,
        confidence: float,
        source: dict[str, object],
        reason: str,
    ) -> CommsDraft:
        """Append the next version and retire the one it replaces."""
        previous = await self.latest(incident, audience)
        version = (previous.version if previous is not None else 0) + 1

        draft = await self._repo.create(
            CommsDraft,
            incident_id=incident.id,
            kind=kind,
            confidence=confidence,
            source=source,
            created_by=created_by,
            actor=self._actor.ref,
            reason=self._actor.reason(reason),
            audience=audience,
            body=body,
            version=version,
        )
        if previous is not None and previous.status == "draft":
            await self._repo.supersede(
                CommsDraft,
                previous.id,
                draft.id,
                actor=self._actor.ref,
                reason=self._actor.reason(f"replaced by v{version}"),
            )
        return draft

    # ---- context ----------------------------------------------------------

    async def context(self, incident: Incident) -> CommsContext:
        """Assemble what a draft may be written from."""
        summary = await self._session.scalar(
            select(Summary.body)
            .where(Summary.incident_id == incident.id, Summary.scope == "current")
            .order_by(Summary.version.desc())
            .limit(1)
        )
        facts = list(
            await self._session.scalars(
                select(Fact)
                .where(Fact.incident_id == incident.id, Fact.status == "active")
                .order_by(Fact.created_at.desc())
                .limit(CONTEXT_LIMIT)
            )
        )
        hypotheses = list(
            await self._session.scalars(
                select(Hypothesis)
                .where(
                    Hypothesis.incident_id == incident.id,
                    Hypothesis.status.notin_(("rejected", "superseded")),
                )
                .order_by(Hypothesis.likelihood.desc().nullslast())
                .limit(CONTEXT_LIMIT)
            )
        )
        mitigations = list(
            await self._session.scalars(
                select(MitigationOption)
                .where(
                    MitigationOption.incident_id == incident.id,
                    MitigationOption.status.in_(("proposed", "approved")),
                )
                .order_by(MitigationOption.created_at.desc())
                .limit(CONTEXT_LIMIT)
            )
        )

        # A confirmed hypothesis has stopped being speculation
        confirmed_causes = [h for h in hypotheses if h.status == "confirmed"]
        open_causes = [h for h in hypotheses if h.status != "confirmed"]

        context = CommsContext(
            title=incident.title,
            status=incident.status,
            severity=incident.severity,
            summary=summary,
            confirmed=[f.statement for f in facts]
            + [h.statement for h in confirmed_causes],
            hypotheses=[
                f"{h.statement} (likelihood "
                f"{float(h.likelihood):.0%})" if h.likelihood is not None
                else h.statement
                for h in open_causes
            ],
            impact=[f.statement for f in facts if _is_impact(f.statement)],
            mitigations=[m.title or "" for m in mitigations if m.title],
        )
        context.provenance = {
            "fact_ids": [str(f.id) for f in facts],
            "hypothesis_ids": [str(h.id) for h in hypotheses],
            "confirmed_hypothesis_ids": [str(h.id) for h in confirmed_causes],
            "summary": bool(summary),
        }
        return context

    # ---- internals --------------------------------------------------------

    async def _scoped(self, incident: Incident, draft_id: uuid.UUID) -> CommsDraft:
        draft = await self._session.scalar(
            select(CommsDraft).where(
                CommsDraft.id == draft_id, CommsDraft.incident_id == incident.id
            )
        )
        if draft is None:
            raise NotFoundError(
                f"comms draft {draft_id} not found for incident {incident.id}"
            )
        return draft


#: Words that mark a fact as being about who/what is affected. 
_IMPACT_WORDS = (
    "customer",
    "merchant",
    "user",
    "checkout",
    "order",
    "affected",
    "impact",
    "fail",
    "error rate",
    "% of",
)


def _is_impact(statement: str | None) -> bool:
    text = (statement or "").lower()
    return any(word in text for word in _IMPACT_WORDS)


def _validate_audience(audience: str) -> None:
    if audience not in COMMS_AUDIENCES:
        raise ValidationError(
            f"audience must be one of: {', '.join(COMMS_AUDIENCES)}"
        )


__all__ = ["AGENT_DRAFT_CONFIDENCE", "CommsService", "DraftResult"]
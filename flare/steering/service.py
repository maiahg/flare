from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.agents.reconciler import CorrectionCandidate, CorrectionReconciler
from flare.events.outbox import commit_and_publish
from flare.llm import LLMClient
from flare.memory import MemoryRepository
from flare.memory.spec import OP_UPDATE, entity_type
from flare.models.claims import (
    ACTION_ITEM_STATUSES,
    OPEN_QUESTION_STATUSES,
    ActionItem,
    CommsDraft,
    Decision,
    Evidence,
    Fact,
    Hypothesis,
    OpenQuestion,
    PostmortemDraft,
    TimelineEntry,
)
from flare.models.core import INCIDENT_MODES, Incident, User, Workspace
from flare.postmortem import generate_postmortem
from flare.steering.actors import Actor
from flare.steering.errors import NotFoundError, ValidationError

#: Statuses a human may set from the steering surface, per claim type
FACT_STATUSES = ("active", "stale", "rejected")
EVIDENCE_STATUSES = ("stale",)
HUMAN_HYPOTHESIS_STATUSES = ("confirmed", "rejected", "proposed")

#: Provenance for a claim a human authored directly.
HUMAN_KIND = "human_statement"
HUMAN_CONFIDENCE = 1.0

#: How many existing claims a correction is reconciled against.
CORRECTION_CANDIDATES = 25


@dataclass
class CorrectionOutcome:
    """What a ``POST /corrections`` actually did."""

    fact_id: uuid.UUID
    invalidated: list[tuple[str, uuid.UUID]] = field(default_factory=list)
    note: str = ""


@dataclass
class ManualRunRequest:
    """The manual-investigation payload handed to the worker after commit."""

    incident_id: uuid.UUID
    target: str | None
    since: str | None
    focus: str | None

    def trigger(self, actor: Actor) -> dict[str, Any]:
        """A trigger payload shaped like the ones triage produces."""
        ask = " ".join(filter(None, (self.target, self.focus))).strip()
        return {
            "reason": "manual_investigate",
            "command": "/flare investigate",
            "user_id": actor.user_id,
            "target": self.target,
            "since": self.since,
            "focus": self.focus,
            "messages": [{"text": ask, "user_id": actor.user_id}],
            "signals": [
                {
                    "type": "command",
                    "text": ask or "manual investigation",
                    "novel": True,
                    "category": "command",
                    "reason": "explicit human request",
                }
            ],
        }


class SteeringService:
    """Human writes against one incident's memory."""

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

    @property
    def actor(self) -> Actor:
        return self._actor

    # ---- transaction boundary --------------------------------------------

    def defer(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run ``hook`` after the transaction commits (job enqueues, posts)."""
        self._after_commit.append(hook)

    async def commit(self, *refresh: Any) -> None:
        """Commit, publish the queued SSE events, then run deferred hooks."""
        await commit_and_publish(self._session)
        for entity in refresh:
            if entity is not None:
                await self._session.refresh(entity)
        hooks, self._after_commit = self._after_commit, []
        for hook in hooks:
            await hook()

    # ---- incidents --------------------------------------------------------

    async def create_incident(
        self,
        *,
        title: str,
        description: str | None = None,
        channel_id: str | None = None,
        alert_payload: Mapping[str, Any] | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> Incident:
        """Open an incident"""
        if not title.strip():
            raise ValidationError("title is required")
        if workspace_id is None:
            workspace_ids = list(await self._session.scalars(select(Workspace.id)))
            if len(workspace_ids) != 1:
                raise ValidationError(
                    "workspace_id is required "
                    f"({len(workspace_ids)} workspaces installed)"
                )
            workspace_id = workspace_ids[0]

        incident = Incident(
            workspace_id=workspace_id,
            slack_channel_id=channel_id,
            title=title.strip(),
            description=description,
            status="open",
            mode="assist",
            started_at=datetime.now(UTC),
            alert_payload=dict(alert_payload) if alert_payload else None,
            source={"type": "human", "surface": self._actor.surface},
            created_by=self._actor.ref,
        )
        self._session.add(incident)
        await self._session.flush()
        await self._journal_incident(
            incident,
            before=None,
            after={"title": incident.title, "status": incident.status},
            action="opened incident",
        )
        return incident

    async def set_mode(self, incident: Incident, mode: str) -> Incident:
        """Set the behavior mode."""
        if mode not in INCIDENT_MODES:
            raise ValidationError(
                f"mode must be one of: {', '.join(INCIDENT_MODES)}"
            )
        previous = incident.mode
        if previous == mode:
            return incident
        incident.mode = mode
        await self._session.flush()
        await self._journal_incident(
            incident,
            before={"mode": previous},
            after={"mode": mode},
            action=f"set mode to {mode}",
        )
        return incident

    async def request_investigation(
        self,
        incident: Incident,
        *,
        target: str | None = None,
        since: str | None = None,
        focus: str | None = None,
    ) -> ManualRunRequest:
        """Ask for a targeted read-only run"""
        request = ManualRunRequest(
            incident_id=incident.id, target=target, since=since, focus=focus
        )
        await self._journal_incident(
            incident,
            before={"investigation_requested": False},
            after={
                "investigation_requested": True,
                "target": target,
                "since": since,
                "focus": focus,
            },
            action="requested an investigation",
        )
        return request

    # ---- claims -----------------------------------------------------------

    async def patch_fact(
        self,
        incident: Incident,
        fact_id: uuid.UUID,
        *,
        statement: str | None = None,
        status: str | None = None,
    ) -> Fact:
        """Correct a fact's wording and/or its status."""
        self._validate_status(status, FACT_STATUSES, "fact")
        changes: dict[str, Any] = {}
        if statement is not None:
            if not statement.strip():
                raise ValidationError("statement cannot be empty")
            changes["statement"] = statement.strip()
        return await self._apply(
            Fact, incident, fact_id, changes, status, action="corrected fact"
        )

    async def patch_hypothesis(
        self,
        incident: Incident,
        hypothesis_id: uuid.UUID,
        *,
        status: str | None = None,
        rank: int | None = None,
    ) -> Hypothesis:
        """Confirm or reject a hypothesis, optionally re-ranking it"""
        self._validate_status(status, HUMAN_HYPOTHESIS_STATUSES, "hypothesis")
        changes: dict[str, Any] = {}
        if rank is not None:
            changes["rank"] = rank
        return await self._apply(
            Hypothesis,
            incident,
            hypothesis_id,
            changes,
            status,
            action=f"{status or 'updated'} hypothesis",
        )

    async def mark_evidence_stale(
        self, incident: Incident, evidence_id: uuid.UUID
    ) -> Evidence:
        """Mark an observation stale"""
        await self._scoped(Evidence, incident, evidence_id)
        return await self._repo.mark_stale(
            Evidence,
            evidence_id,
            actor=self._actor.ref,
            reason=self._actor.reason("marked evidence stale"),
        )

    async def patch_question(
        self,
        incident: Incident,
        question_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID | None = None,
        status: str | None = None,
        answer: str | None = None,
    ) -> OpenQuestion:
        """Assign an owner, record an answer, or close a question."""
        self._validate_status(status, OPEN_QUESTION_STATUSES, "question")
        changes: dict[str, Any] = {}
        if owner_user_id is not None:
            await self._require_user(owner_user_id)
            changes["owner_user_id"] = owner_user_id
        if answer is not None:
            changes["answer"] = answer.strip()
            status = status or "answered"
        return await self._apply(
            OpenQuestion,
            incident,
            question_id,
            changes,
            status,
            action="updated question",
        )

    async def create_action_item(
        self,
        incident: Incident,
        *,
        description: str,
        owner_user_id: uuid.UUID | None = None,
        due_at: datetime | None = None,
    ) -> ActionItem:
        """Add a follow-up the humans own."""
        if not description.strip():
            raise ValidationError("description is required")
        if owner_user_id is not None:
            await self._require_user(owner_user_id)
        return await self._repo.create(
            ActionItem,
            incident_id=incident.id,
            kind=HUMAN_KIND,
            confidence=HUMAN_CONFIDENCE,
            source=self._source(),
            created_by=self._actor.ref,
            actor=self._actor.ref,
            reason=self._actor.reason("created action item"),
            description=description.strip(),
            owner_user_id=owner_user_id,
            due_at=due_at,
        )

    async def patch_action_item(
        self,
        incident: Incident,
        action_item_id: uuid.UUID,
        *,
        status: str | None = None,
        owner_user_id: uuid.UUID | None = None,
    ) -> ActionItem:
        self._validate_status(status, ACTION_ITEM_STATUSES, "action item")
        changes: dict[str, Any] = {}
        if owner_user_id is not None:
            await self._require_user(owner_user_id)
            changes["owner_user_id"] = owner_user_id
        return await self._apply(
            ActionItem,
            incident,
            action_item_id,
            changes,
            status,
            action="updated action item",
        )

    async def approve_comms(
        self, incident: Incident, comms_id: uuid.UUID
    ) -> CommsDraft:
        """Mark a comms draft approved"""
        return await self._apply(
            CommsDraft,
            incident,
            comms_id,
            {},
            "approved",
            action="approved comms draft",
        )

    # ---- corrections ------------------------------------------------------

    async def submit_correction(
        self,
        incident: Incident,
        *,
        correction_text: str,
        target_entity_type: str | None = None,
        target_entity_id: uuid.UUID | None = None,
    ) -> CorrectionOutcome:
        """Record a human correction and reconcile memory against it"""
        text = correction_text.strip()
        if not text:
            raise ValidationError("correction_text is required")

        fact = await self._repo.create(
            Fact,
            incident_id=incident.id,
            kind=HUMAN_KIND,
            confidence=HUMAN_CONFIDENCE,
            source=self._source(
                correction=True,
                target_entity_type=target_entity_type,
                target_entity_id=str(target_entity_id) if target_entity_id else None,
            ),
            created_by=self._actor.ref,
            actor=self._actor.ref,
            reason=self._actor.reason("submitted a correction"),
            statement=text,
        )
        outcome = CorrectionOutcome(fact_id=fact.id)

        if target_entity_id is not None:
            model = self._correctable_model(target_entity_type)
            await self._scoped(model, incident, target_entity_id)
            await self._repo.reject(
                model,
                target_entity_id,
                actor=self._actor.ref,
                reason=f"corrected: {text}",
            )
            outcome.invalidated.append((entity_type(model), target_entity_id))
            return outcome

        if self._llm is None:
            return outcome

        candidates = await self._correction_candidates(incident)
        reconciler = CorrectionReconciler(self._llm)
        chosen, note = await reconciler.run(correction=text, candidates=candidates)
        outcome.note = note
        for candidate in chosen:
            model = self._correctable_model(candidate.entity_type)
            await self._repo.reject(
                model,
                uuid.UUID(candidate.entity_id),
                actor=self._actor.ref,
                reason=f"corrected: {text}",
            )
            outcome.invalidated.append((candidate.entity_type, uuid.UUID(candidate.entity_id)))
        return outcome

    async def _correction_candidates(
        self, incident: Incident
    ) -> list[CorrectionCandidate]:
        """Active facts + hypotheses a correction could plausibly invalidate."""
        candidates: list[CorrectionCandidate] = []
        for model, text_field, active in (
            (Fact, "statement", "active"),
            (Hypothesis, "statement", None),
        ):
            stmt = select(model).where(model.incident_id == incident.id)
            if active is not None:
                stmt = stmt.where(model.status == active)
            else:
                stmt = stmt.where(model.status.notin_(("rejected", "superseded")))
            stmt = stmt.order_by(model.created_at.desc()).limit(CORRECTION_CANDIDATES)
            for row in await self._session.scalars(stmt):
                candidates.append(
                    CorrectionCandidate(
                        entity_type=entity_type(model),
                        entity_id=str(row.id),
                        text=str(getattr(row, text_field) or ""),
                    )
                )
        return candidates

    @staticmethod
    def _correctable_model(name: str | None) -> type[Any]:
        """Map an ``entity_type`` string to the model a correction may reject."""
        models: dict[str, type[Any]] = {
            entity_type(m): m
            for m in (Fact, Hypothesis, Decision, TimelineEntry, OpenQuestion)
        }
        model = models.get(str(name))
        if model is None:
            raise ValidationError(
                f"entity_type must be one of: {', '.join(sorted(models))}"
            )
        return model

    # ---- postmortem -------------------------------------------------------

    async def generate_postmortem(self, incident: Incident) -> PostmortemDraft:
        """Assemble a postmortem draft from current memory"""
        return await generate_postmortem(
            self._session,
            incident,
            actor=self._actor,
            llm=self._llm,
            model=self._model,
        )

    # ---- internals --------------------------------------------------------

    def _source(self, **extra: Any) -> dict[str, Any]:
        """The ``source`` envelope for a claim a human authored."""
        return {
            "type": "human",
            "surface": self._actor.surface,
            "user_id": self._actor.user_id,
            **{k: v for k, v in extra.items() if v is not None},
        }

    @staticmethod
    def _validate_status(
        status: str | None, allowed: Sequence[str], label: str
    ) -> None:
        if status is not None and status not in allowed:
            raise ValidationError(
                f"{label} status must be one of: {', '.join(allowed)}"
            )

    async def _scoped(
        self, model: type[Any], incident: Incident, entity_id: uuid.UUID
    ) -> Any:
        """Fetch an entity, refusing ids that belong to another incident."""
        row = await self._session.scalar(
            select(model).where(
                model.id == entity_id, model.incident_id == incident.id
            )
        )
        if row is None:
            raise NotFoundError(
                f"{entity_type(model)} {entity_id} not found for incident "
                f"{incident.id}"
            )
        return row

    async def _require_user(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return user

    async def _apply(
        self,
        model: type[Any],
        incident: Incident,
        entity_id: uuid.UUID,
        changes: dict[str, Any],
        status: str | None,
        *,
        action: str,
    ) -> Any:
        """Route a patch to the journal op that describes it."""
        await self._scoped(model, incident, entity_id)
        reason = self._actor.reason(action)

        if status is not None and not changes:
            if status == "rejected":
                return await self._repo.reject(
                    model, entity_id, actor=self._actor.ref, reason=reason
                )
            if status == "stale":
                return await self._repo.mark_stale(
                    model, entity_id, actor=self._actor.ref, reason=reason
                )

        if status is not None:
            changes["status"] = status
        if not changes:
            raise ValidationError("nothing to change")
        return await self._repo.update(
            model, entity_id, changes, actor=self._actor.ref, reason=reason
        )

    async def _journal_incident(
        self,
        incident: Incident,
        *,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        action: str,
    ) -> None:
        """Journal a change to the incident row itself (not a claim table)."""
        await self._repo.record_change(
            entity_type_name=entity_type(Incident),
            entity_id=incident.id,
            incident_id=incident.id,
            op=OP_UPDATE if before is not None else "create",
            before=before,
            after=after,
            actor=self._actor.ref,
            reason=self._actor.reason(action),
        )


__all__ = [
    "EVIDENCE_STATUSES",
    "FACT_STATUSES",
    "HUMAN_HYPOTHESIS_STATUSES",
    "CorrectionOutcome",
    "ManualRunRequest",
    "SteeringService",
]
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from flare.api.v1.deps import ActorDep
from flare.api.v1.incidents import IncidentDep, SessionDep
from flare.api.v1.schemas import (
    ActionItemCreate,
    ActionItemPatch,
    ActionItemRead,
    ApprovalDecision,
    ApprovalRead,
    CommsDraftPatch,
    CommsDraftRead,
    CommsGenerate,
    CorrectionCreate,
    CorrectionResult,
    EvidencePatch,
    EvidenceRead,
    FactPatch,
    FactRead,
    HypothesisPatch,
    HypothesisRead,
    IncidentCreate,
    IncidentRead,
    InvestigateRequest,
    ModeUpdate,
    OpenQuestionRead,
    PostmortemDraftRead,
    QuestionPatch,
    RunAccepted,
    StatusUpdate,
)
from flare.approvals import decide_approval
from flare.comms import CommsService
from flare.config import get_settings
from flare.llm import get_llm_client
from flare.models.audit import Approval
from flare.models.claims import (
    ActionItem,
    CommsDraft,
    Evidence,
    Fact,
    Hypothesis,
    OpenQuestion,
    PostmortemDraft,
)
from flare.models.core import Incident
from flare.steering import SteeringService, ValidationError
from flare.steering.service import EVIDENCE_STATUSES
from flare.worker.enqueue import enqueue_adaptive_run

router = APIRouter(tags=["steering"])


async def _service(session: SessionDep, actor: ActorDep) -> SteeringService:
    """A steering service bound to this request's session + actor."""
    return SteeringService(
        session,
        actor,
        llm=get_llm_client(),
        model=get_settings().llm.models.postmortem,
    )


ServiceDep = Annotated[SteeringService, Depends(_service)]


async def _comms(session: SessionDep, actor: ActorDep) -> CommsService:
    """The comms-draft writer for this request. It has no way to send anything."""
    return CommsService(
        session,
        actor,
        llm=get_llm_client(),
        model=get_settings().llm.models.comms,
    )


CommsDep = Annotated[CommsService, Depends(_comms)]


# ---- incidents -------------------------------------------------------------


@router.post(
    "/incidents",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident(
    body: IncidentCreate, service: ServiceDep
) -> Incident:
    """Open an incident."""
    incident = await service.create_incident(
        title=body.title,
        description=body.description,
        channel_id=body.channel_id,
        alert_payload=body.alert_payload,
        workspace_id=body.workspace_id,
    )
    await service.commit(incident)
    return incident


@router.post("/incidents/{incident_id}/mode", response_model=IncidentRead)
async def set_mode(
    incident: IncidentDep, body: ModeUpdate, service: ServiceDep
) -> Incident:
    """Set the behavior mode: quiet | scribe | assist | active."""
    updated = await service.set_mode(incident, body.mode)
    await service.commit(updated)
    return updated


@router.post("/incidents/{incident_id}/status", response_model=IncidentRead)
async def set_status(
    incident: IncidentDep, body: StatusUpdate, service: ServiceDep
) -> Incident:
    """Move the incident status: open | mitigating | monitoring | resolved | closed."""
    updated = await service.set_status(incident, body.status)
    await service.commit(updated)
    return updated


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def investigate(
    incident: IncidentDep, body: InvestigateRequest, service: ServiceDep
) -> RunAccepted:
    """Queue a manual, targeted, read-only run."""
    request = await service.request_investigation(
        incident, target=body.target, since=body.since, focus=body.focus
    )
    trigger = request.trigger(service.actor)

    async def _enqueue() -> None:
        await enqueue_adaptive_run(
            {
                "incident_id": str(incident.id),
                "created_by": service.actor.ref,
                "trigger": trigger,
            }
        )

    # Deferred: the worker reads the rows this request wrote, so it must not
    # start before the commit that created them.
    service.defer(_enqueue)
    await service.commit()
    return RunAccepted(
        incident_id=incident.id, target=body.target, focus=body.focus
    )


# ---- claims ----------------------------------------------------------------


@router.patch("/incidents/{incident_id}/facts/{fact_id}", response_model=FactRead)
async def patch_fact(
    incident: IncidentDep,
    fact_id: uuid.UUID,
    body: FactPatch,
    service: ServiceDep,
) -> Fact:
    """Correct a fact's wording, or mark it stale/rejected."""
    fact = await service.patch_fact(
        incident, fact_id, statement=body.statement, status=body.status
    )
    await service.commit(fact)
    return fact


@router.patch(
    "/incidents/{incident_id}/hypotheses/{hypothesis_id}",
    response_model=HypothesisRead,
)
async def patch_hypothesis(
    incident: IncidentDep,
    hypothesis_id: uuid.UUID,
    body: HypothesisPatch,
    service: ServiceDep,
) -> Hypothesis:
    """Confirm or reject a hypothesis."""
    hypothesis = await service.patch_hypothesis(
        incident, hypothesis_id, status=body.status, rank=body.rank
    )
    await service.commit(hypothesis)
    return hypothesis


@router.patch(
    "/incidents/{incident_id}/evidence/{evidence_id}", response_model=EvidenceRead
)
async def patch_evidence(
    incident: IncidentDep,
    evidence_id: uuid.UUID,
    body: EvidencePatch,
    service: ServiceDep,
) -> Evidence:
    """Mark evidence stale — the only mutation an observation allows."""
    if body.status not in EVIDENCE_STATUSES:
        raise ValidationError(
            f"evidence status may only be: {', '.join(EVIDENCE_STATUSES)}"
        )
    evidence = await service.mark_evidence_stale(incident, evidence_id)
    await service.commit(evidence)
    return evidence


@router.patch(
    "/incidents/{incident_id}/questions/{question_id}",
    response_model=OpenQuestionRead,
)
async def patch_question(
    incident: IncidentDep,
    question_id: uuid.UUID,
    body: QuestionPatch,
    service: ServiceDep,
) -> OpenQuestion:
    """Assign an owner, record an answer, or close a question."""
    question = await service.patch_question(
        incident,
        question_id,
        owner_user_id=body.owner_user_id,
        status=body.status,
        answer=body.answer,
    )
    await service.commit(question)
    return question


@router.post(
    "/incidents/{incident_id}/action-items",
    response_model=ActionItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_action_item(
    incident: IncidentDep, body: ActionItemCreate, service: ServiceDep
) -> ActionItem:
    item = await service.create_action_item(
        incident,
        description=body.description,
        owner_user_id=body.owner_user_id,
        due_at=body.due_at,
    )
    await service.commit(item)
    return item


@router.patch(
    "/incidents/{incident_id}/action-items/{action_item_id}",
    response_model=ActionItemRead,
)
async def patch_action_item(
    incident: IncidentDep,
    action_item_id: uuid.UUID,
    body: ActionItemPatch,
    service: ServiceDep,
) -> ActionItem:
    item = await service.patch_action_item(
        incident,
        action_item_id,
        status=body.status,
        owner_user_id=body.owner_user_id,
    )
    await service.commit(item)
    return item


@router.post(
    "/incidents/{incident_id}/comms/generate",
    response_model=CommsDraftRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_comms(
    incident: IncidentDep, body: CommsGenerate, comms: CommsDep
) -> CommsDraft:
    """Write the next version of one audience's draft."""
    result = await comms.generate(incident, audience=body.audience)
    await comms.commit(result.draft)
    return result.draft


@router.patch(
    "/incidents/{incident_id}/comms/{comms_id}", response_model=CommsDraftRead
)
async def edit_comms(
    incident: IncidentDep,
    comms_id: uuid.UUID,
    body: CommsDraftPatch,
    comms: CommsDep,
) -> CommsDraft:
    """Edit a draft — stored as a new version, so the old text stays readable."""
    result = await comms.revise(incident, body=body.body, edited_from=comms_id)
    await comms.commit(result.draft)
    return result.draft


@router.post(
    "/incidents/{incident_id}/comms/{comms_id}/approve",
    response_model=CommsDraftRead,
)
async def approve_comms(
    incident: IncidentDep, comms_id: uuid.UUID, service: ServiceDep
) -> CommsDraft:
    """Approve a draft. Approval marks it approved; it never sends."""
    draft = await service.approve_comms(incident, comms_id)
    await service.commit(draft)
    return draft
    

@router.post(
    "/incidents/{incident_id}/approvals/{approval_id}", response_model=ApprovalRead
)
async def decide(
    incident: IncidentDep,
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    session: SessionDep,
    actor: ActorDep,
) -> Approval:
    """Approve or reject a gated recommendation"""
    return await decide_approval(
        session,
        actor,
        incident=incident,
        approval_id=approval_id,
        decision=body.decision,
        note=body.note,
    )

# ---- corrections + postmortem ----------------------------------------------


@router.post(
    "/incidents/{incident_id}/corrections",
    response_model=CorrectionResult,
    status_code=status.HTTP_201_CREATED,
)
async def submit_correction(
    incident: IncidentDep,
    body: CorrectionCreate,
    service: ServiceDep,
    session: SessionDep,
) -> CorrectionResult:
    """Record a human correction; Scribe reconciles what it invalidates."""
    outcome = await service.submit_correction(
        incident,
        correction_text=body.correction_text,
        target_entity_type=body.entity_type,
        target_entity_id=body.entity_id,
    )
    await service.commit()
    fact = await session.get(Fact, outcome.fact_id)
    assert fact is not None  # just written in this transaction
    return CorrectionResult(
        fact=FactRead.model_validate(fact),
        invalidated=[
            {"entity_type": kind, "entity_id": str(eid)}
            for kind, eid in outcome.invalidated
        ],
        note=outcome.note,
    )


@router.post(
    "/incidents/{incident_id}/postmortem/generate",
    response_model=PostmortemDraftRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_postmortem(
    incident: IncidentDep, service: ServiceDep
) -> PostmortemDraft:
    """Generate (or regenerate) the postmortem draft from current memory."""
    draft = await service.generate_postmortem(incident)
    await service.commit(draft)
    return draft
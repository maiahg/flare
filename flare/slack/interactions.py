from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.llm import get_llm_client
from flare.models.claims import Evidence, EvidenceLink, Hypothesis
from flare.models.core import Incident
from flare.slack.blocks import (
    ACTION_APPROVAL_APPROVE,
    ACTION_APPROVAL_REJECT,
    ACTION_HYPOTHESIS_CONFIRM,
    ACTION_HYPOTHESIS_EVIDENCE,
    ACTION_HYPOTHESIS_INVESTIGATE,
    ACTION_HYPOTHESIS_REJECT,
    ACTION_QUESTION_ANSWERED,
    ACTION_QUESTION_ASSIGN,
)
from flare.approvals import decide_approval
from flare.comms import CommsService
from flare.slack.incident_ops import incident_for_channel, resolve_user
from flare.slack.modals import (
    ACTION_COMMS_AUDIENCE,
    BLOCK_COMMS_BODY,
    CALLBACK_COMMS_DRAFT,
    SlackModals,
    loading_view,
    parse_metadata,
    submitted_body,
)
from flare.steering import Actor, SteeringError, SteeringService, slack_actor
from flare.worker.enqueue import enqueue_adaptive_run, enqueue_comms_draft

_logger = logging.getLogger("flare.slack.interactions")


Responder = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _post_response(url: str, payload: dict[str, Any]) -> None:
    """Send a follow-up to Slack's ``response_url`` (best effort)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json=payload)
    except Exception:  
        _logger.warning("failed to post interaction response", exc_info=True)


def dashboard_url(incident_id: uuid.UUID) -> str:
    base = str(get_settings().app_base_url).rstrip("/")
    return f"{base}/incidents/{incident_id}"


async def handle_interaction(
    payload: dict[str, Any], *, responder: Responder | None = None
) -> dict[str, Any]:
    """Dispatch one Slack interaction. Returns the ACK body (for tests + logs)."""
    if payload.get("type") == "view_submission":
        return await handle_view_submission(payload)
    if payload.get("type") == "view_closed":
        return {"ok": True, "status": "closed"}
    if payload.get("type") != "block_actions":
        return {"ok": True, "status": "ignored"}

    if payload.get("view"):
        return await _handle_view_action(payload)

    actions = payload.get("actions") or []
    if not actions:
        return {"ok": True, "status": "ignored"}
    action = actions[0]
    action_id = str(action.get("action_id", ""))

    user = payload.get("user") or {}
    team_id = str((payload.get("team") or {}).get("id", ""))
    channel_id = str((payload.get("channel") or {}).get("id", ""))
    actor = slack_actor(str(user.get("id", "")), user.get("name"))
    if not actor.user_id:
        return {"ok": True, "status": "ignored"}

    send = responder if responder is not None else _post_response
    response_url = payload.get("response_url")

    async with get_sessionmaker()() as session:
        incident = await incident_for_channel(session, channel_id, team_id=team_id)
        if incident is None:
            text = "This channel isn't tracking a flare incident."
            await _reply(send, response_url, text)
            return {"ok": True, "status": "no_incident", "text": text}

        try:
            result = await _dispatch(
                session, incident, actor, action_id, action, payload
            )
        except SteeringError as exc:
            await session.rollback()
            await _reply(send, response_url, f":warning: {exc}")
            return {"ok": True, "status": "rejected", "text": str(exc)}
        except Exception as exc:  # noqa: BLE001 - surface, don't 500 at Slack
            await session.rollback()
            _logger.exception("interaction %s failed", action_id)
            await _reply(send, response_url, f":warning: {exc}")
            return {"ok": True, "status": "error", "text": str(exc)}

    await _reply(send, response_url, result["text"])
    return {"ok": True, **result}


async def _reply(send: Responder, url: str | None, text: str) -> None:
    if url:
        await send(url, {"response_type": "ephemeral", "text": text})


async def _dispatch(
    session: AsyncSession,
    incident: Incident,
    actor: Actor,
    action_id: str,
    action: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run one action against the steering service and describe the outcome."""
    service = SteeringService(session, actor, llm=get_llm_client())
    value = str(action.get("value") or "")

    if action_id == ACTION_HYPOTHESIS_EVIDENCE:
        return {
            "status": "read",
            "text": await _evidence_summary(session, incident, uuid.UUID(value)),
        }

    if action_id in (ACTION_HYPOTHESIS_CONFIRM, ACTION_HYPOTHESIS_REJECT):
        status = (
            "confirmed" if action_id == ACTION_HYPOTHESIS_CONFIRM else "rejected"
        )
        hypothesis = await service.patch_hypothesis(
            incident, uuid.UUID(value), status=status
        )
        await service.commit(hypothesis)
        note = (
            " It will not be re-proposed by a later run."
            if status == "rejected"
            else ""
        )
        return {
            "status": status,
            "entity_id": value,
            "text": f":white_check_mark: Hypothesis *{status}*.{note}",
        }

    if action_id == ACTION_HYPOTHESIS_INVESTIGATE:
        statement = await session.scalar(
            select(Hypothesis.statement).where(Hypothesis.id == uuid.UUID(value))
        )
        request = await service.request_investigation(
            incident, target=None, focus=statement
        )
        trigger = request.trigger(actor)
        service.defer(
            lambda: enqueue_adaptive_run(
                {
                    "incident_id": str(incident.id),
                    "created_by": actor.ref,
                    "trigger": trigger,
                }
            )
        )
        await service.commit()
        return {
            "status": "queued",
            "entity_id": value,
            "text": ":mag: On it — checking that hypothesis.",
        }

    if action_id == ACTION_QUESTION_ASSIGN:
        assignee = str(action.get("selected_user") or action.get("value") or "")
        if not assignee:
            return {"status": "ignored", "text": "No user selected."}
        owner = await resolve_user(session, incident.workspace_id, assignee)
        question_id = _entity_from_block(payload, action, prefix="question")
        question = await service.patch_question(
            incident, question_id, owner_user_id=owner.id
        )
        await service.commit(question)
        return {
            "status": "assigned",
            "entity_id": str(question_id),
            "owner": assignee,
            "text": f":bust_in_silhouette: Assigned to <@{assignee}>.",
        }

    if action_id == ACTION_QUESTION_ANSWERED:
        question = await service.patch_question(
            incident, uuid.UUID(value), status="answered"
        )
        await service.commit(question)
        return {
            "status": "answered",
            "entity_id": value,
            "text": ":white_check_mark: Question marked answered.",
        }

    if action_id in (ACTION_APPROVAL_APPROVE, ACTION_APPROVAL_REJECT):
        decision = "approved" if action_id == ACTION_APPROVAL_APPROVE else "rejected"
        approval = await decide_approval(
            session,
            actor,
            incident=incident,
            approval_id=uuid.UUID(value),
            decision=decision,
        )
        return {
            "status": approval.status,
            "entity_id": value,
            "text": (
                f":shield: Mitigation *{approval.status}* — recorded as intent. "
                "Flare does not apply mitigations."
            ),
        }

    return {"status": "unknown_action", "text": f"Unsupported action {action_id}."}


def _entity_from_block(
    payload: dict[str, Any], action: dict[str, Any], *, prefix: str
) -> uuid.UUID:
    """Recover the entity id for elements that can't carry a ``value``."""
    block_id = str(action.get("block_id") or "")
    if not block_id:
        for block in payload.get("message", {}).get("blocks", []):
            candidate = str(block.get("block_id", ""))
            if candidate.startswith(f"{prefix}:"):
                block_id = candidate
                break
    _, _, raw = block_id.partition(":")
    return uuid.UUID(raw)


async def _handle_view_action(payload: dict[str, Any]) -> dict[str, Any]:
    """Switching the audience selector refills the modal for that audience."""
    actions = payload.get("actions") or []
    action = actions[0] if actions else {}
    if str(action.get("action_id", "")) != ACTION_COMMS_AUDIENCE:
        return {"ok": True, "status": "ignored"}

    view = payload.get("view") or {}
    metadata = parse_metadata(view.get("private_metadata"))
    incident_id = metadata.get("incident_id")
    audience = str((action.get("selected_option") or {}).get("value") or "")
    if not incident_id or not audience:
        return {"ok": True, "status": "ignored"}

    view_id = str(view.get("id") or "")
    if view_id:
        try:
            await SlackModals().update(
                view_id=view_id,
                view=loading_view(
                    incident_id=uuid.UUID(incident_id), audience=audience
                ),
            )
        except Exception: 
            _logger.warning("failed to show the loading view", exc_info=True)
    await enqueue_comms_draft(
        {
            "incident_id": incident_id,
            "audience": audience,
            "view_id": view_id or None,
            "user_id": str((payload.get("user") or {}).get("id", "")),
        }
    )
    return {"ok": True, "status": "drafting", "audience": audience}


async def handle_view_submission(payload: dict[str, Any]) -> dict[str, Any]:
    """Save any edit as a new version, then approve it. """
    view = payload.get("view") or {}
    if str(view.get("callback_id", "")) != CALLBACK_COMMS_DRAFT:
        return {}

    metadata = parse_metadata(view.get("private_metadata"))
    incident_id = metadata.get("incident_id")
    draft_id = metadata.get("draft_id")
    if not incident_id or not draft_id:
        return _view_error("This draft is still being written — try again.")

    actor = slack_actor(
        str((payload.get("user") or {}).get("id", "")),
        (payload.get("user") or {}).get("name"),
    )
    body = submitted_body(view)

    async with get_sessionmaker()() as session:
        incident = await session.get(Incident, uuid.UUID(incident_id))
        if incident is None:
            return _view_error("That incident no longer exists.")
        comms = CommsService(session, actor)
        try:
            revision = await comms.revise(
                incident, body=body, edited_from=uuid.UUID(draft_id)
            )
            steering = SteeringService(session, actor)
            await steering.approve_comms(incident, revision.draft.id)
            await comms.commit()
        except SteeringError as exc:
            await session.rollback()
            return _view_error(str(exc))
        except Exception as exc:  # noqa: BLE001 - show it in the modal, don't 500
            await session.rollback()
            _logger.exception("comms approval failed")
            return _view_error(str(exc))

    return {"response_action": "clear"}


def _view_error(message: str) -> dict[str, Any]:
    """Slack's inline-error shape, attached to the body input."""
    return {"response_action": "errors", "errors": {BLOCK_COMMS_BODY: message}}


async def _evidence_summary(
    session: AsyncSession, incident: Incident, hypothesis_id: uuid.UUID
) -> str:
    """The linked evidence for one hypothesis, as a short ephemeral list."""
    rows = (
        await session.execute(
            select(Evidence.title, Evidence.system, EvidenceLink.relation)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(
                EvidenceLink.incident_id == incident.id,
                EvidenceLink.subject_type == "hypothesis",
                EvidenceLink.subject_id == hypothesis_id,
            )
            .order_by(EvidenceLink.created_at)
            .limit(10)
        )
    ).all()
    link = dashboard_url(incident.id)
    if not rows:
        return f"No evidence is linked to that hypothesis yet. <{link}|Dashboard →>"
    lines = [
        f"• _{relation}_ [{system}] {title}" for title, system, relation in rows
    ]
    return "*Linked evidence*\n" + "\n".join(lines) + f"\n<{link}|Evidence board →>"


__all__ = [
    "Responder",
    "dashboard_url",
    "handle_interaction",
    "handle_view_submission",
]
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.models.claims import (
    Decision,
    Evidence,
    EvidenceLink,
    Fact,
    Hypothesis,
    OpenQuestion,
    Summary,
)
from flare.models.core import Incident, User
from flare.slack.blocks import ephemeral, hypothesis_card, question_card


LIMIT = 5


async def hypotheses_view(
    session: AsyncSession, incident: Incident, dashboard_url: str
) -> dict[str, Any]:
    """Ranked hypotheses with support/contradict counts + action buttons."""
    rows = list(
        await session.scalars(
            select(Hypothesis)
            .where(
                Hypothesis.incident_id == incident.id,
                Hypothesis.status != "superseded",
            )
            .order_by(
                Hypothesis.rank.nulls_last(), Hypothesis.likelihood.desc().nullslast()
            )
            .limit(LIMIT)
        )
    )
    if not rows:
        return ephemeral(f"No hypotheses yet. Dashboard: {dashboard_url}")

    counts = await _evidence_counts(session, incident, [h.id for h in rows])
    blocks: list[dict[str, Any]] = []
    for h in rows:
        supporting, contradicting = counts.get(h.id, (0, 0))
        blocks.extend(
            hypothesis_card(
                hypothesis_id=h.id,
                statement=h.statement,
                likelihood=float(h.likelihood) if h.likelihood is not None else None,
                status=h.status,
                supporting=supporting,
                contradicting=contradicting,
                dashboard_url=dashboard_url,
            )
        )
        blocks.append({"type": "divider"})
    return ephemeral(f"{len(rows)} hypotheses", blocks[:-1])


async def _evidence_counts(
    session: AsyncSession, incident: Incident, hypothesis_ids: list[Any]
) -> dict[Any, tuple[int, int]]:
    """(supporting, contradicting) per hypothesis, in one query."""
    rows = await session.execute(
        select(
            EvidenceLink.subject_id, EvidenceLink.relation, func.count()
        )
        .where(
            EvidenceLink.incident_id == incident.id,
            EvidenceLink.subject_type == "hypothesis",
            EvidenceLink.subject_id.in_(hypothesis_ids),
        )
        .group_by(EvidenceLink.subject_id, EvidenceLink.relation)
    )
    counts: dict[Any, tuple[int, int]] = {}
    for subject_id, relation, total in rows:
        supporting, contradicting = counts.get(subject_id, (0, 0))
        if relation == "contradicts":
            contradicting += int(total)
        elif relation == "supports":
            supporting += int(total)
        counts[subject_id] = (supporting, contradicting)
    return counts


async def evidence_view(
    session: AsyncSession,
    incident: Incident,
    dashboard_url: str,
    *,
    system: str | None = None,
) -> dict[str, Any]:
    """Evidence board snapshot, optionally filtered with `--system logs`."""
    stmt = select(Evidence).where(Evidence.incident_id == incident.id)
    if system:
        stmt = stmt.where(Evidence.system == system)
    rows = list(
        await session.scalars(stmt.order_by(Evidence.created_at.desc()).limit(LIMIT))
    )
    if not rows:
        scope = f" from {system}" if system else ""
        return ephemeral(f"No evidence{scope} yet. Dashboard: {dashboard_url}")
    lines = [
        f"• [{e.system}] *{e.title}*"
        + (" _(stale)_" if e.status == "stale" else "")
        + f"\n   {(e.body or '')[:180]}"
        for e in rows
    ]
    return ephemeral(
        "*Evidence*\n" + "\n".join(lines) + f"\n\n<{dashboard_url}|Evidence board →>"
    )


async def questions_view(
    session: AsyncSession, incident: Incident, dashboard_url: str
) -> dict[str, Any]:
    """Open questions with Assign / Mark answered controls."""
    rows = list(
        await session.scalars(
            select(OpenQuestion)
            .where(
                OpenQuestion.incident_id == incident.id,
                OpenQuestion.status == "open",
            )
            .order_by(OpenQuestion.created_at)
            .limit(LIMIT)
        )
    )
    if not rows:
        return ephemeral(f"No open questions. Dashboard: {dashboard_url}")

    owners = await _owner_handles(session, [q.owner_user_id for q in rows])
    blocks: list[dict[str, Any]] = []
    for q in rows:
        blocks.extend(
            question_card(
                question_id=q.id,
                question=q.question,
                owner=owners.get(q.owner_user_id),
                status=q.status,
                dashboard_url=dashboard_url,
            )
        )
        blocks.append({"type": "divider"})
    return ephemeral(f"{len(rows)} open questions", blocks[:-1])


async def _owner_handles(
    session: AsyncSession, user_ids: list[Any]
) -> dict[Any, str]:
    wanted = [uid for uid in user_ids if uid is not None]
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.slack_user_id).where(User.id.in_(wanted))
    )
    return {uid: f"<@{slack_id}>" for uid, slack_id in rows}


async def decisions_view(
    session: AsyncSession, incident: Incident, dashboard_url: str
) -> dict[str, Any]:
    """The decision log."""
    rows = list(
        await session.scalars(
            select(Decision)
            .where(Decision.incident_id == incident.id, Decision.status != "rejected")
            .order_by(Decision.created_at)
            .limit(LIMIT * 2)
        )
    )
    if not rows:
        return ephemeral(f"No decisions recorded. Dashboard: {dashboard_url}")
    lines = [
        f"• {d.statement}" + (f" _(by {d.decided_by})_" if d.decided_by else "")
        for d in rows
    ]
    return ephemeral("*Decisions*\n" + "\n".join(lines) + f"\n\n<{dashboard_url}|→>")


async def brief_view(
    session: AsyncSession, incident: Incident, dashboard_url: str
) -> dict[str, Any]:
    """Current state in one message: summary, top hypotheses, open questions."""
    summary = await session.scalar(
        select(Summary.body)
        .where(Summary.incident_id == incident.id, Summary.scope == "current")
        .order_by(Summary.version.desc())
        .limit(1)
    )
    top = list(
        await session.scalars(
            select(Hypothesis.statement)
            .where(
                Hypothesis.incident_id == incident.id,
                Hypothesis.status.notin_(("rejected", "superseded")),
            )
            .order_by(Hypothesis.likelihood.desc().nullslast())
            .limit(3)
        )
    )
    questions = list(
        await session.scalars(
            select(OpenQuestion.question)
            .where(
                OpenQuestion.incident_id == incident.id,
                OpenQuestion.status == "open",
            )
            .order_by(OpenQuestion.created_at)
            .limit(3)
        )
    )
    facts = await session.scalar(
        select(func.count())
        .select_from(Fact)
        .where(Fact.incident_id == incident.id, Fact.status == "active")
    )

    parts = [
        f":fire: *{incident.title}* — {incident.status} / {incident.severity} "
        f"/ mode {incident.mode}",
        summary or "_No summary yet._",
        "*Top hypotheses*\n" + ("\n".join(f"• {t}" for t in top) or "• none yet"),
        "*Open questions*\n" + ("\n".join(f"• {q}" for q in questions) or "• none"),
        f"_{int(facts or 0)} active facts_ · <{dashboard_url}|Full incident →>",
    ]
    return ephemeral("\n\n".join(parts))


def dashboard_view(dashboard_url: str) -> dict[str, Any]:
    return ephemeral(f"Dashboard for this incident: {dashboard_url}")
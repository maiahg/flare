from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from flare.agents.schemas import GroundedClaim, PostmortemOutput
from flare.llm import LLMClient, LLMUsage
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data


PROMPT_LIMIT = 20


@dataclass(frozen=True)
class EvidenceRef:
    """One evidence row, in the shape a citation needs."""

    id: uuid.UUID
    system: str
    title: str
    body: str
    query: str | None = None
    tool_call_id: uuid.UUID | None = None
    status: str = "active"

    def cite(self) -> dict[str, Any]:
        return {
            "kind": "evidence",
            "id": str(self.id),
            "system": self.system,
            "title": self.title,
            "query": self.query,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "stale": self.status == "stale",
        }


@dataclass(frozen=True)
class MemoryRef:
    """A citation of a memory row that is not evidence (a fact, a decision…)."""

    entity_type: str
    entity_id: uuid.UUID
    created_by: str | None = None
    kind: str | None = None

    def cite(self) -> dict[str, Any]:
        return {
            "kind": "memory",
            "entity_type": self.entity_type,
            "id": str(self.entity_id),
            "created_by": self.created_by,
            "claim_kind": self.kind,
        }


@dataclass(frozen=True)
class CauseCandidate:
    """A hypothesis and the evidence that supports it."""

    id: uuid.UUID
    statement: str
    status: str
    likelihood: float | None
    supporting: tuple[EvidenceRef, ...] = ()
    contradicting: tuple[EvidenceRef, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass
class PostmortemMemory:
    """Everything the draft may be written from, already read out of the DB."""

    title: str
    status: str
    severity: str
    started_at: datetime | None = None
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None
    summary: str | None = None
    summary_ref: MemoryRef | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    causes: list[CauseCandidate] = field(default_factory=list)
    facts: list[tuple[str, MemoryRef]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[tuple[str, MemoryRef]] = field(default_factory=list)
    action_items: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def choose_cause(causes: Sequence[CauseCandidate]) -> CauseCandidate | None:
    """The root cause the draft will state, or ``None`` if none is grounded."""
    grounded = [c for c in causes if c.supporting and c.status != "rejected"]
    if not grounded:
        return None
    confirmed = [c for c in grounded if c.confirmed]
    pool = confirmed or grounded
    return max(pool, key=lambda c: (c.likelihood or 0.0, len(c.supporting)))


def entry(
    text: str,
    *,
    evidence: Iterable[EvidenceRef] = (),
    memory: MemoryRef | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One line of the draft, carrying the provenance that justifies it."""
    citations = [ref.cite() for ref in evidence]
    if memory is not None:
        citations.append(memory.cite())
    return {"text": text, "provenance": citations, **extra}


def ground(
    claims: Iterable[GroundedClaim], evidence: Sequence[EvidenceRef]
) -> tuple[list[dict[str, Any]], int]:
    """Resolve cited indices to evidence; drop claims that cite none."""
    entries: list[dict[str, Any]] = []
    dropped = 0
    for claim in claims:
        text = (claim.text or "").strip()
        refs = [
            evidence[i]
            for i in dict.fromkeys(claim.evidence_indices)
            if 0 <= i < len(evidence)
        ]
        if not text or not refs:
            dropped += 1
            continue
        entries.append(entry(text, evidence=refs))
    return entries, dropped


_SYSTEM = """You are PostmortemAgent for an incident copilot.
{untrusted}

You are drafting sections of an incident postmortem for engineers who were not
present. Every sentence you write MUST cite the numbered EVIDENCE it rests on,
by index, in evidence_indices.

Rules:
- A claim you cannot cite must be omitted. Do not hedge it, do not soften it —
  leave it out.
- The ROOT CAUSE has already been determined from memory and is given to you.
  Explain it using the evidence listed under it; do not propose a different
  cause.
- impact: what was affected and how much, from the evidence.
- contributing_factors: conditions that made the incident possible or worse.
- No blame, no speculation about people, no recommendations (follow-ups are
  tracked separately). Return the schema."""


class PostmortemAgent:
    """Writes the narrative sections; the citations are enforced in code."""

    agent_name = "PostmortemAgent"

    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(
        self, memory: PostmortemMemory, *, cause: CauseCandidate | None
    ) -> tuple[dict[str, list[dict[str, Any]]], int]:
        """Return ``({section: entries}, dropped_uncited)``."""
        evidence = memory.evidence[:PROMPT_LIMIT]
        result = await self._llm.structured(
            schema=PostmortemOutput,
            system=_SYSTEM.format(untrusted=UNTRUSTED_DATA_RULE),
            user=as_data(_prompt(memory, cause, evidence), label="INCIDENT MEMORY"),
            model=self._model,
            trace_name="postmortem.draft",
        )
        self.usage.add(result)

        impact, dropped_impact = ground(result.value.impact, evidence)
        factors, dropped_factors = ground(result.value.contributing_factors, evidence)
        narrative, dropped_cause = _ground_cause(result.value.root_cause, cause)
        return (
            {
                "impact": impact,
                "contributing_factors": factors,
                "root_cause_narrative": narrative,
            },
            dropped_impact + dropped_factors + dropped_cause,
        )


def _ground_cause(
    claims: Iterable[GroundedClaim], cause: CauseCandidate | None
) -> tuple[list[dict[str, Any]], int]:
    """Root-cause prose may only cite the chosen cause's own evidence."""
    if cause is None:
        return [], sum(1 for _ in claims)
    return ground(claims, cause.supporting)


def _prompt(
    memory: PostmortemMemory,
    cause: CauseCandidate | None,
    evidence: Sequence[EvidenceRef],
) -> str:
    lines = [
        f"INCIDENT: {memory.title} ({memory.severity}, {memory.status})",
        f"SUMMARY: {memory.summary or 'none recorded'}",
        "",
        "EVIDENCE (cite these by index):",
        *(
            f"[{i}] ({ref.system}{', STALE' if ref.status == 'stale' else ''}) "
            f"{ref.title}: {ref.body}"
            for i, ref in enumerate(evidence)
        ),
        "",
        "ROOT CAUSE (determined from memory — explain, do not replace):",
    ]
    if cause is None:
        lines.append("- undetermined; no hypothesis has supporting evidence")
    else:
        lines.append(f"- {cause.statement} [{cause.status}]")
        lines += [
            f"  supported by [{evidence.index(ref)}] {ref.title}"
            if ref in evidence
            else f"  supported by {ref.title}"
            for ref in cause.supporting
        ]
    lines += [
        "",
        "TIMELINE:",
        *(f"- {t.get('at') or '?'} {t.get('text', '')}" for t in memory.timeline),
        "",
        "KNOWN FACTS:",
        *(f"- {text}" for text, _ in memory.facts),
    ]
    if memory.limitations:
        lines += ["", "WHAT WE COULD NOT SEE:", *(f"- {x}" for x in memory.limitations)]
    return "\n".join(lines)


__all__ = [
    "PROMPT_LIMIT",
    "CauseCandidate",
    "EvidenceRef",
    "MemoryRef",
    "PostmortemAgent",
    "PostmortemMemory",
    "choose_cause",
    "entry",
    "ground",
]
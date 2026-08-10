from __future__ import annotations

from dataclasses import dataclass, field

from flare.agents.schemas import CommsDraftOutput
from flare.llm import LLMClient, LLMUsage, redact
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data
from flare.models.claims import COMMS_AUDIENCES

#: Hard cap on a generated draft.
MAX_BODY_CHARS = 1200

#: Audiences that may be shown unconfirmed hypotheses.
INTERNAL_AUDIENCES = frozenset({"internal", "exec"})

_AUDIENCE_GUIDANCE: dict[str, str] = {
    "internal": (
        "Responders and engineering. Be specific: current symptoms, the leading "
        "hypothesis (explicitly labelled as a hypothesis, not a cause), what is "
        "being checked next, and what help is needed."
    ),
    "support": (
        "Frontline support agents talking to customers. Say what a customer "
        "would notice, what agents should tell them, and what not to promise. "
        "No internal service names, no cause, no timelines."
    ),
    "status": (
        "A public status page. Say what is affected and that we are working on "
        "it, in one short paragraph. No cause, no internal names, no blame, no "
        "commitment to a resolution time. Say when the next update will come."
    ),
    "exec": (
        "Leadership. Lead with business impact and scope, then current state and "
        "whether a decision is needed. No jargon, no per-service detail."
    ),
}

_SYSTEM = """You are CommsAgent for an incident copilot.
{untrusted}

Write ONE incident update for this audience:
{guidance}

Rules:
- Use only the facts given. If something is unknown, say it is unknown; never
  invent a cause, a number, a customer count, or a time.
- Present tense, plain language, no marketing tone, no apologies for things we
  have not confirmed.
- Keep it under {max_words} words. Return the schema."""


class UnknownAudienceError(ValueError):
    """Raised for an audience outside the §3.2 vocabulary."""


@dataclass
class CommsContext:
    """The memory a draft may be written from, assembled by the caller."""

    title: str
    status: str
    severity: str
    summary: str | None = None
    #: Confirmed statements: safe for every audience.
    confirmed: list[str] = field(default_factory=list)
    #: Candidate explanations: internal audiences only.
    hypotheses: list[str] = field(default_factory=list)
    #: What is known about who/what is affected.
    impact: list[str] = field(default_factory=list)
    #: Mitigations a human has approved as intent.
    mitigations: list[str] = field(default_factory=list)
    #: Which memory rows this context was built from
    provenance: dict[str, object] = field(default_factory=dict)

    def for_audience(self, audience: str) -> str:
        """The prompt payload this audience is allowed to see."""
        lines = [
            f"INCIDENT: {self.title}",
            f"STATE: {self.status} / severity {self.severity}",
            f"CURRENT SUMMARY: {self.summary or 'none recorded'}",
            *_block("CONFIRMED", self.confirmed, empty="nothing confirmed yet"),
            *_block("IMPACT", self.impact, empty="not yet quantified"),
        ]
        if audience in INTERNAL_AUDIENCES:
            lines += _block(
                "UNCONFIRMED HYPOTHESES (label them as such)",
                self.hypotheses,
                empty="none",
            )
            lines += _block(
                "MITIGATIONS UNDER CONSIDERATION", self.mitigations, empty="none"
            )
        return "\n".join(lines)


def _block(label: str, items: list[str], *, empty: str) -> list[str]:
    return [f"{label}:", *(f"- {item}" for item in items or [f"({empty})"])]


class CommsAgent:
    """Turns incident memory into one audience's draft. Never sends anything."""

    agent_name = "CommsAgent"

    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(self, *, audience: str, context: CommsContext) -> str:
        if audience not in COMMS_AUDIENCES:
            raise UnknownAudienceError(
                f"audience must be one of: {', '.join(COMMS_AUDIENCES)}"
            )
        result = await self._llm.structured(
            schema=CommsDraftOutput,
            system=_SYSTEM.format(
                untrusted=UNTRUSTED_DATA_RULE,
                guidance=_AUDIENCE_GUIDANCE[audience],
                max_words=MAX_BODY_CHARS // 8,
            ),
            user=as_data(context.for_audience(audience), label="INCIDENT MEMORY"),
            model=self._model,
            trace_name=f"comms.draft.{audience}",
        )
        self.usage.add(result)
        return clean_body(result.value.body)


def clean_body(body: str) -> str:
    """Redact and bound a draft body — applied to model *and* human text."""
    text = redact((body or "").strip())
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[: MAX_BODY_CHARS - 1].rstrip() + "…"


def fallback_body(audience: str, context: CommsContext) -> str:
    """A draft assembled without a model, for when the LLM is unavailable."""
    if audience in INTERNAL_AUDIENCES:
        head = f"{context.title} ({context.severity}, {context.status})."
    else:
        head = "We are investigating an issue affecting some customers."
    parts = [head]
    if context.summary:
        parts.append(context.summary)
    elif context.confirmed:
        parts.append(context.confirmed[0])
    parts.append("We will share another update as soon as we know more.")
    return clean_body(" ".join(parts))


__all__ = [
    "INTERNAL_AUDIENCES",
    "MAX_BODY_CHARS",
    "CommsAgent",
    "CommsContext",
    "UnknownAudienceError",
    "clean_body",
    "fallback_body",
]
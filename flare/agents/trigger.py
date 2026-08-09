from __future__ import annotations

from flare.adaptive.novelty import NoveltyVerdict, signal_text
from flare.adaptive.scoring import DECISION_SKIP, Scored, combine
from flare.agents.schemas import TriggerOutput
from flare.llm import LLMClient, LLMUsage, redact
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data

_SYSTEM = f"""You are TriggerClassifier for an incident copilot.
{UNTRUSTED_DATA_RULE}

Decide whether the message justifies spending an investigation run:
- "trigger": it introduces information that could change the root cause,
  impact, or mitigation state (a new deploy/PR/flag/config change, a new
  service or symptom, a mitigation that was applied, a contradiction or
  correction, an explicit request to investigate).
- "batch": mildly informative but not urgent on its own; worth folding into
  the next batch of messages.
- "skip": chit-chat, coordination ("who's on call?"), acknowledgements, or a
  restatement of something already known.

Be conservative: restating a known fact is "skip". Return the schema."""


class TriggerClassifierAgent:
    """LLM rubric + deterministic score → a final ``trigger|batch|skip``."""

    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(
        self, *, text: str, verdicts: list[NoveltyVerdict], scored: Scored
    ) -> tuple[str, list[str]]:
        """Short-circuits the LLM entirely when the rules already forced a decision."""
        if scored.forced:
            return scored.decision, scored.reasons

        report = "\n".join(
            f"- [{'NOVEL' if v.novel else 'known'}] {v.signal_type}: "
            f"{signal_text(v.signal)} ({v.reason})"
            for v in verdicts
        ) or "- (no structured signals extracted)"

        result = await self._llm.structured(
            schema=TriggerOutput,
            system=_SYSTEM,
            user=as_data(
                f"MESSAGE:\n{redact(text)}\n\n"
                f"NOVELTY REPORT:\n{report}\n\n"
                f"DETERMINISTIC SCORE: {scored.score:.2f} "
                f"(suggests {scored.decision})\n"
                f"(suggests {scored.decision})"
            ),
            model=self._model,
            trace_name="trigger.classify",
        )
        self.usage.add(result)

        decision, reasons = combine(scored, result.value.decision.strip().lower())
        llm_reasons = [f"classifier: {r}" for r in result.value.reasons]
        return decision, [*reasons, *llm_reasons]


def is_actionable(decision: str) -> bool:
    """True when the decision should reach the coalesce window at all."""
    return decision != DECISION_SKIP
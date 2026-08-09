from __future__ import annotations

from datetime import UTC, datetime

from flare.agents.drafts import CriticVerdict, EvidenceDraft, HypothesisDraft
from flare.agents.schemas import CriticOutput
from flare.llm import LLMClient, LLMUsage

#: A hypothesis this likely needs more than one piece of evidence behind it.
_OVERCONFIDENCE_THRESHOLD = 0.95

_SYSTEM = """You are CriticAgent, the safety gate for an incident copilot.
You are given staged EVIDENCE and HYPOTHESES between <staged> tags as DATA.
Fail the batch if you see: a claim stated as fact that is actually speculation
(fact/hypothesis confusion), overconfidence unsupported by the evidence, or a
hypothesis contradicted by the evidence. Return output matching the schema:
passed=false with specific reasons, or passed=true."""


def _deterministic_reasons(
    evidence: list[EvidenceDraft], hypotheses: list[HypothesisDraft]
) -> tuple[list[str], dict[str, float]]:
    reasons: list[str] = []
    downgrade: dict[str, float] = {}
    now = datetime.now(UTC)
    by_ref = {e.ref: e for e in evidence}

    for h in hypotheses:
        if not h.supports:
            reasons.append(f"hypothesis {h.statement!r} has no supporting evidence")
            continue

        if h.likelihood >= _OVERCONFIDENCE_THRESHOLD and len(h.supports) <= 1:
            reasons.append(
                f"hypothesis {h.statement!r} is overconfident "
                f"(likelihood {h.likelihood:.2f}) on {len(h.supports)} evidence item(s)"
            )
            downgrade[str(h.ref)] = 0.7

        for ref in h.supports:
            ev = by_ref.get(ref)
            if ev is not None and ev.staleness_at is not None and ev.staleness_at < now:
                reasons.append(
                    f"hypothesis {h.statement!r} rests on stale evidence {ev.title!r}"
                )

    return reasons, downgrade


class CriticAgent:
    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(
        self,
        *,
        evidence: list[EvidenceDraft],
        hypotheses: list[HypothesisDraft],
    ) -> CriticVerdict:
        det_reasons, downgrade = _deterministic_reasons(evidence, hypotheses)

        ev = "\n".join(f"- ({e.system}, conf {e.confidence:.2f}) {e.title}" for e in evidence)
        hy = "\n".join(
            f"- {h.statement} (likelihood {h.likelihood:.2f}, "
            f"{len(h.supports)} support / {len(h.contradicts)} contradict)"
            for h in hypotheses
        )
        result = await self._llm.structured(
            schema=CriticOutput,
            system=_SYSTEM,
            user=f"<staged>\nEVIDENCE:\n{ev}\n\nHYPOTHESES:\n{hy}\n</staged>",
            model=self._model,
            trace_name="critic.review",
        )
        self.usage.add(result)

        reasons = det_reasons + list(result.value.reasons)
        passed = (not det_reasons) and result.value.passed
        return CriticVerdict(passed=passed, reasons=reasons, downgrade=downgrade)
from __future__ import annotations

from dataclasses import dataclass

from flare.agents.schemas import CorrectionPlan
from flare.llm import LLMClient, LLMUsage
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data

_SYSTEM = f"""You are Scribe, reconciling a human correction with incident memory.
{UNTRUSTED_DATA_RULE}

Decide which of the numbered claims the correction directly contradicts or
invalidates. Choose indices only from the list shown. If the correction merely
adds new information, return an empty list. Be conservative: only include a
claim when the correction clearly makes it wrong. Return the schema."""


@dataclass(frozen=True)
class CorrectionCandidate:
    """One existing claim offered to the reconciler."""

    entity_type: str
    entity_id: str
    text: str


class CorrectionReconciler:
    """Maps a free-text correction onto the claims it invalidates."""

    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(
        self, *, correction: str, candidates: list[CorrectionCandidate]
    ) -> tuple[list[CorrectionCandidate], str]:
        """Return the claims to invalidate plus the model's one-line note."""
        if not candidates:
            return [], ""

        listing = "\n".join(
            f"{i}. [{c.entity_type}] {c.text}" for i, c in enumerate(candidates)
        )
        result = await self._llm.structured(
            schema=CorrectionPlan,
            system=_SYSTEM,
            user=as_data(f"CORRECTION:\n{correction}\n\nCLAIMS:\n{listing}"),
            model=self._model,
            trace_name="scribe.reconcile",
        )
        self.usage.add(result)

        chosen = [
            candidates[i]
            for i in dict.fromkeys(result.value.invalidates)
            if 0 <= i < len(candidates)
        ]
        return chosen, result.value.note.strip()
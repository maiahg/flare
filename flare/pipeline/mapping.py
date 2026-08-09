from __future__ import annotations

from dataclasses import dataclass

from flare.agents.schemas import ExtractedSignal


@dataclass(frozen=True)
class ClaimPlan:
    timeline: list[dict]
    facts: list[dict]
    questions: list[dict]
    decisions: list[dict]


def plan_claims(text: str, signals: list[ExtractedSignal]) -> ClaimPlan:
    timeline: list[dict] = [{"entry_type": "observation", "description": text}]
    facts: list[dict] = []
    questions: list[dict] = []
    decisions: list[dict] = []

    for s in signals:
        body = s.value.get("text", "")
        if s.signal_type == "deploy":
            timeline.append({"entry_type": "deploy", "description": body})
        elif s.signal_type in {"symptom", "metric", "error"} and s.confidence >= 0.7:
            facts.append({"statement": body})
        elif s.signal_type == "open_question":
            questions.append({"question": body})
    return ClaimPlan(timeline, facts, questions, decisions)
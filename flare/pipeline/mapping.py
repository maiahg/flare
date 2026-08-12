from __future__ import annotations

from dataclasses import dataclass

from flare.agents.schemas import ExtractedSignal


@dataclass(frozen=True)
class ClaimPlan:
    timeline: list[dict]
    facts: list[dict]
    questions: list[dict]
    decisions: list[dict]
    action_items: list[dict]


#: A trigger phrase alone ("we decided") is not a usable statement; below this
#: length we fall back to the whole message text.
_MIN_BODY = 15


def _statement(signal: ExtractedSignal, text: str) -> str:
    body = (signal.value.get("text", "") or "").strip()
    return body if len(body) > _MIN_BODY else text.strip()


def _dedupe(items: list[dict], key: str) -> list[dict]:
    """Drop repeats (LLM + deterministic guard can name the same message)."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        norm = " ".join((item.get(key) or "").lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(item)
    return out


def plan_claims(text: str, signals: list[ExtractedSignal]) -> ClaimPlan:
    timeline: list[dict] = []
    facts: list[dict] = []
    questions: list[dict] = []
    decisions: list[dict] = []
    action_items: list[dict] = []

    for s in signals:
        body = (s.value.get("text", "") or "").strip()
        if s.signal_type == "deploy":
            if body:
                timeline.append({"entry_type": "deploy", "description": body})
        elif s.signal_type == "mitigation":
            timeline.append({"entry_type": "mitigation", "description": body or text})
            decisions.append({"statement": _statement(s, text)})
        elif s.signal_type in {"symptom", "metric", "error"} and s.confidence >= 0.7:
            statement = _statement(s, text)
            if statement:
                facts.append({"statement": statement})
        elif s.signal_type == "open_question":
            if body:
                questions.append({"question": body})
        elif s.signal_type == "decision":
            decisions.append({"statement": _statement(s, text)})
        elif s.signal_type == "action_item":
            action_items.append({"description": _statement(s, text)})

    return ClaimPlan(
        timeline,
        _dedupe(facts, "statement"),
        questions,
        _dedupe(decisions, "statement"),
        _dedupe(action_items, "description"),
    )

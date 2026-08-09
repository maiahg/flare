from __future__ import annotations

from dataclasses import dataclass

from flare.adaptive.novelty import NoveltyVerdict

DECISION_TRIGGER = "trigger"
DECISION_BATCH = "batch"
DECISION_SKIP = "skip"

#: Ordering used when combining the deterministic decision with the classifier.
DECISION_ORDER = (DECISION_SKIP, DECISION_BATCH, DECISION_TRIGGER)

#: Category weights
WEIGHTS: dict[str, float] = {
    "command": 1.0,
    "correction": 1.0,
    "contradiction": 1.0,
    "change_event": 0.6,
    "mitigation": 0.5,
    "new_error": 0.5,
    "new_segment": 0.5,
    "novel_service": 0.4,
    "new_observation": 0.3,
    "new_time_window": 0.25,
    "symptom": 0.15,
    "question": 0.1,
    "other": 0.05,
}

#: Categories that trigger regardless of score.
_FLOOR_CATEGORIES = frozenset({"command", "correction", "contradiction"})


@dataclass(frozen=True)
class Scored:
    """The deterministic half of a trigger decision."""

    decision: str
    score: float
    reasons: list[str]
    categories: list[str]
    forced: bool


def score_novelty(
    verdicts: list[NoveltyVerdict],
    *,
    trigger_threshold: float,
    batch_threshold: float,
) -> Scored:
    """Deterministic decision from novelty verdicts."""
    novel = [v for v in verdicts if v.novel]
    if not novel:
        return Scored(
            decision=DECISION_SKIP,
            score=0.0,
            reasons=["no novel signals — restatement or chit-chat"],
            categories=[],
            forced=True,
        )

    categories: list[str] = []
    for v in novel:
        if v.category not in categories:
            categories.append(v.category)

    score = min(1.0, sum(WEIGHTS.get(c, WEIGHTS["other"]) for c in categories))
    reasons = [f"{v.category}: {v.reason}" for v in novel]

    floor_hit = sorted(set(categories) & _FLOOR_CATEGORIES)
    if floor_hit:
        return Scored(
            decision=DECISION_TRIGGER,
            score=max(score, trigger_threshold),
            reasons=[f"rule floor ({', '.join(floor_hit)})", *reasons],
            categories=categories,
            forced=True,
        )

    if score >= trigger_threshold:
        decision = DECISION_TRIGGER
    elif score >= batch_threshold:
        decision = DECISION_BATCH
    else:
        decision = DECISION_SKIP
    return Scored(
        decision=decision,
        score=round(score, 3),
        reasons=reasons,
        categories=categories,
        forced=False,
    )


def combine(scored: Scored, classifier_decision: str) -> tuple[str, list[str]]:
    """Merge the deterministic decision with the classifier's."""
    if scored.forced:
        return scored.decision, scored.reasons

    if classifier_decision not in DECISION_ORDER:
        return scored.decision, [*scored.reasons, "classifier returned an unknown decision"]

    if DECISION_ORDER.index(classifier_decision) > DECISION_ORDER.index(scored.decision):
        return classifier_decision, [
            *scored.reasons,
            f"classifier escalated {scored.decision} → {classifier_decision}",
        ]
    if classifier_decision != scored.decision:
        return scored.decision, [
            *scored.reasons,
            f"classifier said {classifier_decision}; score floor holds "
            f"{scored.decision}",
        ]
    return scored.decision, scored.reasons
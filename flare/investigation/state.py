from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from flare.agents.drafts import (
    CriticVerdict,
    EvidenceDraft,
    HypothesisDraft,
    MitigationDraft,
)
from flare.config import RunBudgetSettings


class RunState(TypedDict, total=False):
    incident_id: str
    run_id: str
    trigger: dict[str, Any]
    plan: dict[str, Any]
    evidence: Annotated[list[EvidenceDraft], operator.add]
    hypotheses: list[HypothesisDraft]
    summary: str | None
    critic_verdict: CriticVerdict | None
    revision_count: int
    limitations: Annotated[list[str], operator.add]
    truncated: bool
    tool_call_count: int
    mitigations: list[MitigationDraft]
    pending_approvals: list[str]
    approval_decision: dict[str, Any] | None
    verify_target: dict[str, Any] | None


def budget_exceeded(
    *,
    elapsed_s: float,
    tool_calls: int,
    budget: RunBudgetSettings,
    tokens: int = 0,
) -> str | None:
    """Return a limitation string if any budget dimension is exceeded, else None."""
    if tool_calls > budget.max_tool_calls:
        return f"tool-call budget exceeded ({tool_calls} > {budget.max_tool_calls})"
    if budget.max_tokens and tokens > budget.max_tokens:
        return f"token budget exceeded ({tokens:,} > {budget.max_tokens:,})"
    if elapsed_s > budget.max_wall_clock_s:
        return f"wall-clock budget exceeded ({elapsed_s:.0f}s > {budget.max_wall_clock_s}s)"
    return None
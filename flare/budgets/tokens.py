from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.config import IncidentBudgetSettings, get_settings
from flare.db.session import get_sessionmaker
from flare.models.tracing import AgentTrace, InvestigationRun


@dataclass(frozen=True)
class TokenUsage:
    """Tokens spent, split the way the provider reports them."""

    tokens_in: int = 0
    tokens_out: int = 0
    runs: int = 0

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out

    def as_dict(self) -> dict[str, int]:
        return {
            "in": self.tokens_in,
            "out": self.tokens_out,
            "total": self.total,
            "runs": self.runs,
        }


@dataclass(frozen=True)
class BudgetVerdict:
    """Whether an incident may start another run, and the numbers behind it."""

    allowed: bool
    used: int
    limit: int
    near_cap: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def ratio(self) -> float:
        return self.used / self.limit if self.limit else 0.0

    def limitation(self) -> str:
        """What a refused run records, in the words an on-call will read."""
        return (
            f"incident token budget exhausted: {self.used:,} of {self.limit:,} "
            f"tokens spent; this run was refused before doing any work. Raise "
            f"incident_budget.max_tokens to continue investigating."
        )


async def run_usage(session: AsyncSession, run_id: uuid.UUID) -> TokenUsage:
    """Tokens spent by one run, summed from its agent traces."""
    rows = await session.scalars(
        select(AgentTrace.tokens).where(AgentTrace.run_id == run_id)
    )
    tokens_in = tokens_out = 0
    for tokens in rows:
        if not tokens:
            continue
        tokens_in += int(tokens.get("in", 0) or 0)
        tokens_out += int(tokens.get("out", 0) or 0)
    return TokenUsage(tokens_in=tokens_in, tokens_out=tokens_out, runs=1)


async def incident_usage(
    session: AsyncSession, incident_id: uuid.UUID
) -> TokenUsage:
    """Tokens spent across every run of an incident."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(InvestigationRun.token_in), 0),
                func.coalesce(func.sum(InvestigationRun.token_out), 0),
                func.count(InvestigationRun.id),
            ).where(InvestigationRun.incident_id == incident_id)
        )
    ).one()
    return TokenUsage(tokens_in=int(row[0]), tokens_out=int(row[1]), runs=int(row[2]))


async def check_incident_budget(
    incident_id: uuid.UUID, *, settings: IncidentBudgetSettings | None = None
) -> BudgetVerdict:
    budget = settings or get_settings().incident_budget
    if budget.max_tokens <= 0:
        return BudgetVerdict(allowed=True, used=0, limit=0)

    async with get_sessionmaker()() as session:
        usage = await incident_usage(session, incident_id)

    return BudgetVerdict(
        allowed=usage.total < budget.max_tokens,
        used=usage.total,
        limit=budget.max_tokens,
        near_cap=usage.total >= budget.max_tokens * budget.warn_ratio,
    )


__all__ = [
    "BudgetVerdict",
    "TokenUsage",
    "check_incident_budget",
    "incident_usage",
    "run_usage",
]
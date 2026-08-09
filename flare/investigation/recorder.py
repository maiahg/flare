from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flare.llm import LLMUsage
from flare.models.tracing import AgentTrace, InvestigationRun, ToolCall
from flare.tools import ToolBroker
from flare.tools.synthetic import build_synthetic_broker


@dataclass
class AgentStep:
    """A live agent step: use ``broker`` for tool calls, set the rest on exit."""

    trace_id: uuid.UUID
    broker: ToolBroker
    session: AsyncSession
    output: dict[str, Any] | None = None
    tokens: dict[str, int] | None = None
    model_name: str | None = None
    provider_request_id: str | None = None
    reasoning_summary: str | None = None
    error: str | None = None
    _extra: dict[str, Any] = field(default_factory=dict)

    def record_usage(self, usage: LLMUsage, *, fallback_model: str | None = None) -> None:
        """Stamp an agent's LLM spend onto this trace.

        ``fallback_model`` covers agents that returned before making any call
        (e.g. a read agent whose probes were all empty), so the trace still
        shows which model *would* have run.
        """
        self.tokens = usage.as_dict()
        self.model_name = usage.model or fallback_model
        self.provider_request_id = usage.provider_request_id


class RunRecorder:
    """Owns the ``investigation_runs`` / ``agent_traces`` / ``tool_calls`` rows."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        incident_id: uuid.UUID,
        run_type: str,
        trigger: dict[str, Any],
        created_by: str,
        scenario: str = "db_latency_spike",
    ) -> None:
        self._sm = sessionmaker
        self._incident_id = incident_id
        self._run_type = run_type
        self._trigger = trigger
        self._created_by = created_by
        self._scenario = scenario
        self.run_id: uuid.UUID | None = None
        # Run-level rollup, accumulated as each agent step closes.
        self._total_in = 0
        self._total_out = 0
        self._last_provider_request_id: str | None = None

    async def start(self) -> uuid.UUID:
        """Insert the run row (status=running) and commit so FKs resolve."""
        async with self._sm() as session:
            run = InvestigationRun(
                incident_id=self._incident_id,
                run_type=self._run_type,
                trigger=self._trigger,
                status="running",
                started_at=datetime.now(UTC),
                created_by=self._created_by,
            )
            session.add(run)
            await session.commit()
            self.run_id = run.id
        return self.run_id

    @asynccontextmanager
    async def agent_step(self, agent_name: str, seq: int) -> AsyncIterator[AgentStep]:
        """Open a per-agent session + trace row; commit the trace update on exit."""
        assert self.run_id is not None, "call start() before agent_step()"
        async with self._sm() as session:
            trace = AgentTrace(
                run_id=self.run_id,
                agent_name=agent_name,
                seq=seq,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(trace)
            await session.commit()  # durable before tool calls reference it

            broker = build_synthetic_broker(
                session,
                run_id=self.run_id,
                incident_id=self._incident_id,
                agent_trace_id=trace.id,
                scenario=self._scenario,
            )
            step = AgentStep(trace_id=trace.id, broker=broker, session=session)
            try:
                yield step
            except Exception as exc:  # noqa: BLE001 - record failure on the trace
                trace.status = "error"
                trace.error = str(exc)
                trace.finished_at = datetime.now(UTC)
                await session.commit()
                raise
            else:
                trace.status = "error" if step.error else "ok"
                trace.error = step.error
                trace.output = step.output
                trace.tokens = step.tokens
                trace.model_name = step.model_name
                trace.provider_request_id = step.provider_request_id
                trace.reasoning_summary = step.reasoning_summary
                trace.finished_at = datetime.now(UTC)
                await session.commit()
                if step.tokens:
                    self._total_in += step.tokens.get("in", 0)
                    self._total_out += step.tokens.get("out", 0)
                if step.provider_request_id:
                    self._last_provider_request_id = step.provider_request_id

    async def save_plan(self, plan: dict[str, Any]) -> None:
        """Persist the run's plan so the dashboard can show why these agents ran."""
        assert self.run_id is not None
        async with self._sm() as session:
            run = await session.get(InvestigationRun, self.run_id)
            if run is None:  
                return
            run.plan = plan
            await session.commit()

    async def count_tool_calls(self) -> int:
        assert self.run_id is not None
        async with self._sm() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(ToolCall)
                .where(ToolCall.run_id == self.run_id)
            )
            return int(total or 0)

    async def finish(
        self,
        *,
        status: str,
        limitations: list[str],
        summary: str | None,
        token_in: int | None = None,
        token_out: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        """Close out the run."""
        assert self.run_id is not None
        async with self._sm() as session:
            run = await session.get(InvestigationRun, self.run_id)
            if run is None: 
                return
            run.status = status
            run.finished_at = datetime.now(UTC)
            run.limitations = limitations or None
            run.summary = summary
            run.token_in = self._total_in if token_in is None else token_in
            run.token_out = self._total_out if token_out is None else token_out
            run.provider_request_id = (
                self._last_provider_request_id
                if provider_request_id is None
                else provider_request_id
            )
            await session.commit()
from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flare.tools.broker import ToolBroker
from flare.tools.interface import BaseReadOnlyTool, ReadOnlyTool, ToolResult
from flare.tools.specs import (
    CODE_BLAME,
    DEPLOY_DIFF,
    FLAGS_AUDIT,
    HISTORY_SEARCH,
    LOGS_SEARCH,
    METRICS_QUERY,
    TRACES_QUERY,
    CodeArgs,
    DeployArgs,
    FlagsArgs,
    HistoryArgs,
    LogsArgs,
    MetricsArgs,
    TracesArgs,
)

_SCENARIO_DIR = Path(__file__).parent / "scenarios"


@lru_cache(maxsize=8)
def load_scenario(name: str = "db_latency_spike") -> dict[str, Any]:
    """Load a scenario fixture by name (cached; fixtures are immutable)."""
    path = _SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"no synthetic scenario {name!r} at {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class _ScenarioTool(BaseReadOnlyTool):
    """Base for adapters bound to one scenario."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self._scenario = scenario


class MetricsTool(_ScenarioTool):
    spec = METRICS_QUERY

    async def fetch(self, args: MetricsArgs) -> ToolResult:
        by_service = self._scenario.get("metrics", {})
        if args.service not in by_service or args.metric not in by_service[args.service]:
            return self.degraded_result(
                f"no {args.metric} series recorded for {args.service}",
                service=args.service,
                metric=args.metric,
                series={},
            )
        return ToolResult(
            system=self.system,
            data={
                "service": args.service,
                "metric": args.metric,
                "series": by_service[args.service][args.metric],
            },
        )


class LogsTool(_ScenarioTool):
    spec = LOGS_SEARCH

    async def fetch(self, args: LogsArgs) -> ToolResult:
        if "logs" not in self._scenario:
            return self.degraded_result("no log source available", matches=[])
        query = args.query.lower()
        matches = [
            entry
            for entry in self._scenario.get("logs", [])
            if (not query or query in entry["text"].lower())
            and (args.service is None or entry.get("service") == args.service)
        ][: args.limit]
        return ToolResult(
            system=self.system, data={"query": query, "matches": matches}
        )


class TracesTool(_ScenarioTool):
    spec = TRACES_QUERY

    async def fetch(self, args: TracesArgs) -> ToolResult:
        if "traces" not in self._scenario:
            return self.degraded_result("no trace source available", spans=[])
        traces = self._scenario["traces"]
        cutoff = int(traces.get("available_after_minutes", 0))
        if args.window_minutes > cutoff:
            return self.degraded_result(
                f"trace sampling >{cutoff}m unavailable for a "
                f"{args.window_minutes}m window",
                spans=[],
            )
        return ToolResult(system=self.system, data={"spans": traces.get("spans", [])})


class DeployTool(_ScenarioTool):
    spec = DEPLOY_DIFF

    async def fetch(self, args: DeployArgs) -> ToolResult:
        if "deploys" not in self._scenario:
            return self.degraded_result("no deploy source available", deploys=[])
        deploys = self._scenario["deploys"]
        if args.deploy_id is not None:
            deploys = [d for d in deploys if str(d["id"]) == str(args.deploy_id)]
        return ToolResult(system=self.system, data={"deploys": deploys[: args.limit]})


class CodeTool(_ScenarioTool):
    spec = CODE_BLAME

    async def fetch(self, args: CodeArgs) -> ToolResult:
        by_service = self._scenario.get("code", {})
        if args.service not in by_service:
            return self.degraded_result(
                f"no code history recorded for {args.service}", commits=[]
            )
        return ToolResult(
            system=self.system,
            data={"service": args.service, **by_service[args.service]},
        )


class FlagsTool(_ScenarioTool):
    spec = FLAGS_AUDIT

    async def fetch(self, args: FlagsArgs) -> ToolResult:
        if "flags" not in self._scenario:
            return self.degraded_result("no flag source available", flags=[])
        flags = self._scenario["flags"]
        if args.key is not None:
            flags = [f for f in flags if f["key"] == args.key]
        return ToolResult(system=self.system, data={"flags": flags})


class HistoryTool(_ScenarioTool):
    spec = HISTORY_SEARCH

    async def fetch(self, args: HistoryArgs) -> ToolResult:
        if "history" not in self._scenario:
            return self.degraded_result("no incident history available", entries=[])
        query = args.query.lower()
        entries = [
            e
            for e in self._scenario["history"]
            if not query or query in e.get("title", "").lower()
        ][: args.limit]
        return ToolResult(system=self.system, data={"entries": entries})


def synthetic_tools(scenario: dict[str, Any]) -> list[ReadOnlyTool]:
    """Every synthetic adapter, ready to register on a broker."""
    return [
        MetricsTool(scenario),
        LogsTool(scenario),
        TracesTool(scenario),
        DeployTool(scenario),
        CodeTool(scenario),
        FlagsTool(scenario),
        HistoryTool(scenario),
    ]


def build_synthetic_broker(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    incident_id: uuid.UUID,
    agent_trace_id: uuid.UUID | None = None,
    scenario: str = "db_latency_spike",
    redis: Redis | None = None,
) -> ToolBroker:
    """A :class:`ToolBroker` pre-loaded with the synthetic provider's adapters."""
    broker = ToolBroker(
        session,
        run_id=run_id,
        incident_id=incident_id,
        agent_trace_id=agent_trace_id,
        redis=redis,
    )
    broker.register_all(synthetic_tools(load_scenario(scenario)))
    return broker
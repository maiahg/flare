from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flare.tools.broker import ToolBroker
from flare.tools.interface import ReadOnlyTool, ToolResult

_SCENARIO_DIR = Path(__file__).parent / "scenarios"


@lru_cache(maxsize=8)
def load_scenario(name: str = "db_latency_spike") -> dict[str, Any]:
    """Load a scenario fixture by name (cached; fixtures are immutable)."""
    path = _SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"no synthetic scenario {name!r} at {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class _ScenarioTool:
    """Base for adapters bound to one scenario."""

    name: str
    system: str

    def __init__(self, scenario: dict[str, Any]) -> None:
        self._scenario = scenario


class MetricsTool(_ScenarioTool):
    name = "metrics.query"
    system = "metrics"

    async def read(self, **args: Any) -> ToolResult:
        service = args.get("service", "checkout-api")
        metric = args.get("metric", "p99_ms")
        series = self._scenario.get("metrics", {}).get(service, {}).get(metric, {})
        return ToolResult(
            system=self.system,
            data={"service": service, "metric": metric, "series": series},
        )


class LogsTool(_ScenarioTool):
    name = "logs.search"
    system = "logs"

    async def read(self, **args: Any) -> ToolResult:
        query = str(args.get("query", "")).lower()
        service = args.get("service")
        matches = [
            entry
            for entry in self._scenario.get("logs", [])
            if (not query or query in entry["text"].lower())
            and (service is None or entry.get("service") == service)
        ]
        return ToolResult(system=self.system, data={"query": query, "matches": matches})


class TracesTool(_ScenarioTool):
    name = "traces.query"
    system = "traces"

    async def read(self, **args: Any) -> ToolResult:
        window_minutes = int(args.get("window_minutes", 5))
        traces = self._scenario.get("traces", {})
        limitations: list[str] = []
        cutoff = int(traces.get("available_after_minutes", 0))
        if window_minutes > cutoff:
            limitations.append(
                f"trace sampling >{cutoff}m unavailable for a {window_minutes}m window"
            )
            return ToolResult(system=self.system, data={"spans": []}, limitations=limitations)
        return ToolResult(system=self.system, data={"spans": traces.get("spans", [])})


class DeployTool(_ScenarioTool):
    name = "deploy.diff"
    system = "deploy"

    async def read(self, **args: Any) -> ToolResult:
        deploy_id = args.get("deploy_id")
        deploys = self._scenario.get("deploys", [])
        if deploy_id is not None:
            deploys = [d for d in deploys if str(d["id"]) == str(deploy_id)]
        return ToolResult(system=self.system, data={"deploys": deploys})


class CodeTool(_ScenarioTool):
    name = "code.blame"
    system = "code"

    async def read(self, **args: Any) -> ToolResult:
        service = args.get("service", "payments-svc")
        info = self._scenario.get("code", {}).get(service, {})
        return ToolResult(system=self.system, data={"service": service, **info})


class FlagsTool(_ScenarioTool):
    name = "flags.audit"
    system = "flags"

    async def read(self, **args: Any) -> ToolResult:
        key = args.get("key")
        flags = self._scenario.get("flags", [])
        if key is not None:
            flags = [f for f in flags if f["key"] == key]
        return ToolResult(system=self.system, data={"flags": flags})


class HistoryTool(_ScenarioTool):
    name = "history.search"
    system = "history"

    async def read(self, **args: Any) -> ToolResult:
        query = str(args.get("query", "")).lower()
        entries = [
            e
            for e in self._scenario.get("history", [])
            if not query or query in e.get("title", "").lower()
        ]
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
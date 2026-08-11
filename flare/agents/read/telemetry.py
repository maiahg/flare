from __future__ import annotations

from typing import Any

from flare.agents.read.base import Probe, ReadAgent, plan_service


class TelemetryAgent(ReadAgent):
    agent_name = "TelemetryAgent"
    system = "metrics"

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        service = plan_service(plan)
        p99 = await self._broker.call("metrics.query", service=service, metric="p99_ms")
        errors = await self._broker.call(
            "metrics.query", service=service, metric="error_rate"
        )
        return [
            Probe(p99, f"metrics.query service={service} metric=p99_ms"),
            Probe(errors, f"metrics.query service={service} metric=error_rate"),
        ]
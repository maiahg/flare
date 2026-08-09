from __future__ import annotations

from typing import Any

from flare.agents.read.base import Probe, ReadAgent


class ImpactAgent(ReadAgent):
    agent_name = "ImpactAgent"
    system = "logs"

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        logs = await self._broker.call("logs.search", query="error")
        flags = await self._broker.call("flags.audit")
        return [
            Probe(logs, "logs.search query=error"),
            Probe(flags, "flags.audit (all)"),
        ]
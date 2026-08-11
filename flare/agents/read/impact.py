from __future__ import annotations

from typing import Any

from flare.agents.read.base import Probe, ReadAgent


class ImpactAgent(ReadAgent):
    agent_name = "ImpactAgent"
    system = "logs"

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        logs = await self._broker.call("logs.search", query="error")
        probes = [Probe(logs, "logs.search query=error")]

        if not logs.result.limitations and not logs.result.data.get("matches"):
            recent = await self._broker.call("logs.search")
            probes.append(Probe(recent, "logs.search (recent, unfiltered)"))
        flags = await self._broker.call("flags.audit")
        probes.append(Probe(flags, "flags.audit (all)"))
        return probes
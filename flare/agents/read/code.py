from __future__ import annotations

from typing import Any

from flare.agents.read.base import Probe, ReadAgent, plan_suspect_service

class CodeAgent(ReadAgent):
    agent_name = "CodeAgent"
    system = "code"

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        service = plan_suspect_service(plan)
        brokered = await self._broker.call("code.blame", service=service)
        return [Probe(brokered, f"code.blame service={service}")]
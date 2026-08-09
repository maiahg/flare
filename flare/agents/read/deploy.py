from __future__ import annotations

from typing import Any

from flare.agents.read.base import Probe, ReadAgent


class DeployAgent(ReadAgent):
    agent_name = "DeployAgent"
    system = "deploy"

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        deploy_id = plan.get("deploy_id")
        if deploy_id is not None:
            brokered = await self._broker.call("deploy.diff", deploy_id=deploy_id)
            return [Probe(brokered, f"deploy.diff deploy_id={deploy_id}")]
        brokered = await self._broker.call("deploy.diff")
        return [Probe(brokered, "deploy.diff (all recent)")]
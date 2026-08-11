from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from flare.agents.drafts import EvidenceDraft
from flare.agents.schemas import ReadAgentOutput
from flare.llm import LLMClient, LLMUsage
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data
from flare.tools import BrokeredResult, ToolBroker

_SYSTEM = f"""You are an incident investigation read-agent.
{UNTRUSTED_DATA_RULE}
Summarize only what the data shows into short, factual findings with a
calibrated confidence (0-1). Do not speculate about root cause — that is another
agent's job.

Some reads may be marked UNAVAILABLE. Never infer that something is healthy,
absent, or normal from a read that failed — say what you saw, and nothing about
what you could not see. Return findings matching the schema."""


DEFAULT_SERVICE = "checkout-api"
DEFAULT_SUSPECT_SERVICE = "payments-svc"

def has_content(data: dict[str, Any]) -> bool:
    for value in data.values():
        if isinstance(value, (list, dict, tuple, set)) and value:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def plan_service(plan: dict[str, Any]) -> str:
    return str(plan.get("service") or DEFAULT_SERVICE)


def plan_suspect_service(plan: dict[str, Any]) -> str:
    return str(
        plan.get("suspect_service") or plan.get("service") or DEFAULT_SUSPECT_SERVICE
    )

@dataclass(frozen=True)
class Probe:
    """One broker call the agent made, plus the human-readable query it ran."""

    brokered: BrokeredResult
    query: str


class ReadAgent:
    """Base read agent. Subclass and implement :meth:`gather`."""

    agent_name: str = "ReadAgent"
    system: str = "metrics"

    def __init__(
        self, llm: LLMClient, broker: ToolBroker, *, model: str | None = None
    ) -> None:
        self._llm = llm
        self._broker = broker
        self._model = model
        self.usage = LLMUsage()
        self.limitations: list[str] = []

    async def gather(self, plan: dict[str, Any]) -> list[Probe]:
        """Make the broker calls this agent needs. Override in subclasses."""
        raise NotImplementedError

    async def run(
        self, *, plan: dict[str, Any], memory_snapshot: dict[str, Any] | None = None
    ) -> list[EvidenceDraft]:
        probes = await self.gather(plan)
        self.limitations = [
            f"{p.brokered.result.system}: {limit} (query: {p.query})"
            for p in probes
            for limit in p.brokered.result.limitations
        ]
        usable = [
            p
            for p in probes
            if not p.brokered.result.degraded and p.brokered.result.data
        ]
        if not usable:
            return []

        primary = usable[0]
        payload = "\n".join(
            f"query: {p.query}\n"
            + (
                "UNAVAILABLE: " + "; ".join(p.brokered.result.limitations) + "\n"
                if p.brokered.result.limitations
                else ""
            )
            + f"result: {json.dumps(p.brokered.result.data, default=str)}"
            for p in usable
        )
        result = await self._llm.structured(
            schema=ReadAgentOutput,
            system=_SYSTEM,
            user=as_data(payload, label="TOOL OUTPUT"),
            model=self._model,
            trace_name=f"{self.agent_name}.summarize",
        )
        self.usage.add(result)

        drafts: list[EvidenceDraft] = []
        for finding in result.value.findings:
            drafts.append(
                EvidenceDraft(
                    system=self.system,
                    title=finding.title,
                    body=finding.body,
                    query=primary.query,
                    result_ref=dict(primary.brokered.result.data),
                    tool_call_id=primary.brokered.tool_call_id,
                    confidence=finding.confidence,
                    created_by=self.agent_name,
                )
            )

        if not drafts:
            for p in usable:
                payload = json.dumps(p.brokered.result.data, default=str)
                found = has_content(p.brokered.result.data)
                drafts.append(
                    EvidenceDraft(
                        system=self.system,
                        title=(
                            f"{self.system}: {p.query}"
                            if found
                            else f"{self.system}: {p.query} — no results"
                        ),
                        body=payload[:480] if found else f"no results. {payload}"[:480],
                        query=p.query,
                        result_ref=dict(p.brokered.result.data),
                        tool_call_id=p.brokered.tool_call_id,
                        confidence=0.6 if found else 0.35,
                        created_by=self.agent_name,
                    )
                )
        return drafts
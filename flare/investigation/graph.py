from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from flare.agents.critic import CriticAgent
from flare.agents.hypothesis import HypothesisAgent
from flare.agents.read import CodeAgent, DeployAgent, ImpactAgent, TelemetryAgent
from flare.agents.summarizer import SummarizerAgent
from flare.config import LLMModelSettings, RunBudgetSettings
from flare.investigation.commit import commit_memory
from flare.investigation.recorder import RunRecorder
from flare.investigation.state import RunState, budget_exceeded
from flare.llm import LLMClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class InvestigationPoster(Protocol):
    """Optional Slack side-effects; injected so the graph stays testable offline."""

    async def post_intent(self, checking: list[str]) -> None: ...
    async def post_findings(
        self, *, summary: str | None, top_hypothesis: str | None, dashboard_url: str
    ) -> None: ...


class RunSuperseded(Exception):
    """Raised at a checkpoint when newer context has replaced this run"""


@dataclass
class GraphDeps:
    llm: LLMClient
    recorder: RunRecorder
    sessionmaker: async_sessionmaker[AsyncSession]
    models: LLMModelSettings
    budget: RunBudgetSettings
    semaphore: asyncio.Semaphore
    budget_started: float
    dashboard_url: str = ""
    poster: InvestigationPoster | None = None
    #: Checked at each checkpoint; truthy → abandon the run as superseded.
    cancelled: Callable[[], Awaitable[bool]] | None = None


#: Graph node name -> read-agent class, in fan-out order.
READ_AGENTS = {
    "telemetry": TelemetryAgent,
    "deploy": DeployAgent,
    "code": CodeAgent,
    "impact": ImpactAgent,
}


def build_investigation_graph(
    deps: GraphDeps, *, read_agents: Sequence[str] | None = None
):  # noqa: ANN201 - langgraph CompiledGraph
    """Assemble + compile an investigation graph for one run."""
    selected = [n for n in (read_agents or list(READ_AGENTS)) if n in READ_AGENTS]

    async def checkpoint() -> None:
        """Abort between nodes if this run has been superseded."""
        if deps.cancelled is not None and await deps.cancelled():
            raise RunSuperseded

    async def extract_context(state: RunState) -> RunState:
        if state.get("plan"):
            return {"revision_count": 0}
        trigger = state.get("trigger", {})
        plan = {
            "service": "checkout-api",
            "deploy_id": trigger.get("deploy_id"),
            "suspect_service": "payments-svc",
            "checking": ["metrics", "deploys", "code", "impact"],
        }
        return {"plan": plan, "revision_count": 0}

    async def post_intent(state: RunState) -> RunState:
        if deps.poster is not None:
            await deps.poster.post_intent(state["plan"].get("checking", []))
        return {}

    async def _read_node(state: RunState, agent_cls, name: str, seq: int) -> RunState:
        await checkpoint()
        async with deps.semaphore:
            async with deps.recorder.agent_step(name, seq) as step:
                agent = agent_cls(deps.llm, step.broker, model=deps.models.default)
                drafts = await agent.run(plan=state["plan"])
                step.output = {"evidence": len(drafts)}
                step.record_usage(agent.usage, fallback_model=deps.models.default)
        return {"evidence": drafts}

    async def telemetry(state: RunState) -> RunState:
        return await _read_node(state, TelemetryAgent, "TelemetryAgent", 1)

    async def deploy(state: RunState) -> RunState:
        return await _read_node(state, DeployAgent, "DeployAgent", 2)

    async def code(state: RunState) -> RunState:
        return await _read_node(state, CodeAgent, "CodeAgent", 3)

    async def impact(state: RunState) -> RunState:
        return await _read_node(state, ImpactAgent, "ImpactAgent", 4)

    async def gather_join(state: RunState) -> RunState:
        await checkpoint()
        tool_calls = await deps.recorder.count_tool_calls()
        elapsed = time.monotonic() - deps.budget_started
        limit = budget_exceeded(
            elapsed_s=elapsed, tool_calls=tool_calls, budget=deps.budget
        )
        out: RunState = {"tool_call_count": tool_calls}
        if limit is not None:
            out["truncated"] = True
            out["limitations"] = [f"truncated: {limit}"]
        return out

    async def hypothesis(state: RunState) -> RunState:
        await checkpoint()
        verdict = state.get("critic_verdict")
        critique = (
            verdict.reasons if verdict is not None and not verdict.passed else None
        )
        async with deps.recorder.agent_step("HypothesisAgent", 5) as step:
            agent = HypothesisAgent(deps.llm, model=deps.models.hypothesis)
            hyps = await agent.run(
                evidence=state.get("evidence", []),
                critique=critique,
                previous=state.get("hypotheses", []),
            )
            step.output = {"hypotheses": len(hyps)}
            step.record_usage(agent.usage, fallback_model=deps.models.hypothesis)
        return {"hypotheses": hyps}

    async def summarizer(state: RunState) -> RunState:
        async with deps.recorder.agent_step("SummarizerAgent", 6) as step:
            agent = SummarizerAgent(deps.llm, model=deps.models.summarizer)
            summary = await agent.run(
                evidence=state.get("evidence", []),
                hypotheses=state.get("hypotheses", []),
            )
            step.output = {"len": len(summary)}
            step.record_usage(agent.usage, fallback_model=deps.models.summarizer)
        return {"summary": summary}

    async def critic(state: RunState) -> RunState:
        async with deps.recorder.agent_step("CriticAgent", 7) as step:
            agent = CriticAgent(deps.llm, model=deps.models.critic)
            verdict = await agent.run(
                evidence=state.get("evidence", []),
                hypotheses=state.get("hypotheses", []),
            )
            step.output = {"passed": verdict.passed, "reasons": verdict.reasons}
            step.record_usage(agent.usage, fallback_model=deps.models.critic)
        return {"critic_verdict": verdict}

    async def revise(state: RunState) -> RunState:
        return {"revision_count": state.get("revision_count", 0) + 1}

    async def commit_node(state: RunState) -> RunState:
        await checkpoint()
        verdict = state.get("critic_verdict")
        extra: list[str] = []
        if verdict is not None and not verdict.passed:
            extra = [f"committed despite critic: {r}" for r in verdict.reasons]
        await commit_memory(
            deps.sessionmaker,
            run_id=uuid.UUID(state["run_id"]),
            incident_id=uuid.UUID(state["incident_id"]),
            evidence=state.get("evidence", []),
            hypotheses=state.get("hypotheses", []),
            summary=state.get("summary"),
            verdict=verdict,
        )
        return {"limitations": extra} if extra else {}

    async def post_findings(state: RunState) -> RunState:
        if deps.poster is not None:
            hyps = state.get("hypotheses", [])
            top = hyps[0].statement if hyps else None
            await deps.poster.post_findings(
                summary=state.get("summary"),
                top_hypothesis=top,
                dashboard_url=deps.dashboard_url,
            )
        return {}

    async def persist_run(state: RunState) -> RunState:
        await deps.recorder.finish(
            status="done",
            limitations=state.get("limitations", []),
            summary=state.get("summary"),
        )
        return {}

    def route_after_gather(state: RunState) -> str:
        return "commit" if state.get("truncated") else "hypothesis"

    def route_after_critic(state: RunState) -> str:
        verdict = state.get("critic_verdict")
        if verdict is not None and verdict.passed:
            return "commit"
        if state.get("revision_count", 0) < deps.budget.max_critic_revisions:
            return "revise"
        return "commit"

    node_impls = {
        "telemetry": telemetry,
        "deploy": deploy,
        "code": code,
        "impact": impact,
    }

    g: StateGraph = StateGraph(RunState)
    g.add_node("extract_context", extract_context)
    g.add_node("post_intent", post_intent)
    for read_name in selected:
        g.add_node(read_name, node_impls[read_name])
    g.add_node("gather_join", gather_join)
    g.add_node("hypothesis", hypothesis)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.add_node("revise", revise)
    g.add_node("commit_memory", commit_node)
    g.add_node("post_findings", post_findings)
    g.add_node("persist_run", persist_run)

    g.add_edge(START, "extract_context")
    g.add_edge("extract_context", "post_intent")
    if selected:
        for read_name in selected:
            g.add_edge("post_intent", read_name)
            g.add_edge(read_name, "gather_join")
    else:
        g.add_edge("post_intent", "gather_join")
    g.add_conditional_edges(
        "gather_join",
        route_after_gather,
        {"hypothesis": "hypothesis", "commit": "commit_memory"},
    )
    g.add_edge("hypothesis", "summarizer")
    g.add_edge("summarizer", "critic")
    g.add_conditional_edges(
        "critic",
        route_after_critic,
        {"commit": "commit_memory", "revise": "revise"},
    )
    g.add_edge("revise", "hypothesis")
    g.add_edge("commit_memory", "post_findings")
    g.add_edge("post_findings", "persist_run")
    g.add_edge("persist_run", END)

    return g.compile(checkpointer=MemorySaver())


def build_initial_graph(deps: GraphDeps): 
    """The initial graph: full fan-out over all four read agents."""
    return build_investigation_graph(deps)
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from flare.agents.critic import CriticAgent
from flare.agents.hypothesis import HypothesisAgent
from flare.agents.mitigation import MitigationAgent
from flare.agents.read import CodeAgent, DeployAgent, ImpactAgent, TelemetryAgent
from flare.agents.drafts import VerificationVerdict
from flare.agents.summarizer import SummarizerAgent
from flare.agents.verifier import VerifierAgent
from flare.approvals import SUBJECT_MITIGATION, create_approval
from flare.config import LLMModelSettings, MitigationSettings, RunBudgetSettings
from flare.events.outbox import commit_and_publish
from flare.investigation.commit import (
    commit_memory,
    commit_mitigations,
    commit_verification,
)
from flare.investigation.recorder import RunRecorder
from flare.investigation.state import RunState, budget_exceeded
from flare.llm import LLMClient
from flare.llm.errors import RateLimitedError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class InvestigationPoster(Protocol):
    """Optional Slack side-effects; injected so the graph stays testable offline."""

    async def post_intent(self, checking: list[str]) -> None: ...
    async def post_findings(
        self, *, summary: str | None, top_hypothesis: str | None, dashboard_url: str
    ) -> None: ...
    async def post_verdict(
        self, *, claim: str, verdict: str, rationale: str, dashboard_url: str
    ) -> None: ...


class ApprovalPoster(Protocol):
    """Posts an approval card. Separate from findings: an approval request is a
    needed human confirmation, which §9 lists as always worth a post."""

    async def post_approval(
        self, *, blocks: list[dict[str, Any]], text: str
    ) -> None: ...


class RunSuperseded(Exception):
    """Raised at a checkpoint when newer context has replaced this run (§7.5)."""


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
    cancelled: Callable[[], Awaitable[bool]] | None = None
    mitigation: MitigationSettings = field(default_factory=MitigationSettings)
    approval_poster: ApprovalPoster | None = None
    default_service: str | None = None


#: Graph node name -> read-agent class, in fan-out order.
READ_AGENTS = {
    "telemetry": TelemetryAgent,
    "deploy": DeployAgent,
    "code": CodeAgent,
    "impact": ImpactAgent,
}


def build_investigation_graph(
    deps: GraphDeps, *, read_agents: Sequence[str] | None = None
):
    """Assemble + compile an investigation graph for one run.

    ``read_agents`` selects the fan-out (default: all four). Unknown names are
    ignored; an empty selection still runs the reasoning tail so a planner that
    picks nothing degrades to "re-reason over existing evidence" instead of
    producing a broken graph.
    """
    selected = [n for n in (read_agents or list(READ_AGENTS)) if n in READ_AGENTS]

    async def checkpoint() -> None:
        """Abort between nodes if this run has been superseded (§7.5/§7.7)."""
        if deps.cancelled is not None and await deps.cancelled():
            raise RunSuperseded

    async def extract_context(state: RunState) -> RunState:
        if state.get("plan"):
            return {"revision_count": 0}
        trigger = state.get("trigger", {})
        service = trigger.get("service") or deps.default_service
        plan = {
            "service": service,
            "deploy_id": trigger.get("deploy_id"),
            "suspect_service": trigger.get("suspect_service") or service,
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
                try:
                    drafts = await agent.run(plan=state["plan"])
                except RateLimitedError as exc:
                    drafts = []
                    agent.limitations = [
                        f"{name}: LLM rate limited, findings not summarized ({exc})"
                    ]
                    step.error = "rate limited"
                step.output = {
                    "evidence": len(drafts),
                    "limitations": agent.limitations,
                }
                step.record_usage(agent.usage, fallback_model=deps.models.default)
        return {"evidence": drafts, "limitations": agent.limitations}

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
            elapsed_s=elapsed,
            tool_calls=tool_calls,
            budget=deps.budget,
            tokens=deps.recorder.tokens_used,
        )
        out: RunState = {"tool_call_count": tool_calls}
        if limit is not None:
            out["truncated"] = True
            out["limitations"] = [f"truncated: {limit}"]
        return out

    async def hypothesis(state: RunState) -> RunState:
        # On a retry the critic's objections are already in state (we only reach
        # here again via `revise`, i.e. after a failed verdict). Feeding them
        # back is what makes the retry differ — otherwise the agent re-runs an
        # identical prompt and the critic rejects it identically.
        await checkpoint()
        verdict = state.get("critic_verdict")
        critique = (
            verdict.reasons if verdict is not None and not verdict.passed else None
        )
        async with deps.recorder.agent_step("HypothesisAgent", 5) as step:
            agent = HypothesisAgent(deps.llm, model=deps.models.hypothesis)
            try:
                hyps = await agent.run(
                    evidence=state.get("evidence", []),
                    critique=critique,
                    previous=state.get("hypotheses", []),
                )
            except RateLimitedError as exc:
                hyps = []
                step.error = "rate limited"
                step.output = {"hypotheses": 0}
                step.record_usage(agent.usage, fallback_model=deps.models.hypothesis)
                return {
                    "hypotheses": [],
                    "truncated": True,
                    "limitations": [f"hypothesis ranking skipped: rate limited ({exc})"],
                }
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

    async def verify(state: RunState) -> RunState:
        await checkpoint()
        target = state.get("verify_target") or {}
        claim = str(target.get("statement") or state["plan"].get("focus") or "")
        async with deps.recorder.agent_step("VerifierAgent", 9) as step:
            agent = VerifierAgent(deps.llm, model=deps.models.verifier)
            try:
                verdict = await agent.run(
                    claim=claim, evidence=state.get("evidence", [])
                )
            except RateLimitedError as exc:
                verdict = VerificationVerdict(
                    verdict="inconclusive",
                    rationale=f"verification skipped: rate limited ({exc})",
                    confidence=0.0,
                )
                step.error = "rate limited"
            step.output = {
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "supports": len(verdict.supports),
                "contradicts": len(verdict.contradicts),
            }
            step.record_usage(agent.usage, fallback_model=deps.models.verifier)
        summary = await commit_verification(
            deps.sessionmaker,
            run_id=uuid.UUID(state["run_id"]),
            incident_id=uuid.UUID(state["incident_id"]),
            evidence=state.get("evidence", []),
            target=target,
            verdict=verdict,
        )
        if deps.poster is not None:
            await deps.poster.post_verdict(
                claim=claim,
                verdict=verdict.verdict,
                rationale=verdict.rationale,
                dashboard_url=deps.dashboard_url,
            )
        return {"summary": summary}

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

    async def mitigate(state: RunState) -> RunState:
        """Propose mitigation options (§11.6). Proposals only — nothing applies."""
        async with deps.recorder.agent_step("MitigationAgent", 8) as step:
            agent = MitigationAgent(
                deps.llm,
                model=deps.models.mitigation,
                max_options=deps.mitigation.max_options,
            )
            try:
                drafts = await agent.run(
                    evidence=state.get("evidence", []),
                    hypotheses=state.get("hypotheses", []),
                    summary=state.get("summary"),
                )
            except Exception as exc:  # noqa: BLE001 - degrade; the run is done
                step.error = str(exc)
                drafts = []
            step.output = {
                "options": len(drafts),
                "approval_required": sum(d.approval_required for d in drafts),
            }
            step.record_usage(agent.usage, fallback_model=deps.models.mitigation)
            failure = step.error
        if not drafts:
            return {"limitations": [f"no mitigation options: {failure}"]} if failure else {}
        option_ids = await commit_mitigations(
            deps.sessionmaker,
            run_id=uuid.UUID(state["run_id"]),
            incident_id=uuid.UUID(state["incident_id"]),
            drafts=drafts,
        )
        gated = [
            str(option_id)
            for option_id, draft in zip(option_ids, drafts, strict=True)
            if draft.approval_required
        ]
        return {"mitigations": drafts, "pending_approvals": gated}

    async def approval_gate(state: RunState) -> RunState:
        gated = state.get("pending_approvals", [])
        if not gated:
            return {}

        incident_id = uuid.UUID(state["incident_id"])
        approvals: list[dict[str, str]] = []
        async with deps.sessionmaker() as session:
            for option_id in gated:
                approval = await create_approval(
                    session,
                    incident_id=incident_id,
                    subject_type=SUBJECT_MITIGATION,
                    subject_id=uuid.UUID(option_id),
                    requested_by="MitigationAgent",
                    note=f"proposed by run {state['run_id']}",
                )
                approvals.append(
                    {"approval_id": str(approval.id), "option_id": option_id}
                )
            await commit_and_publish(session)

        if deps.approval_poster is not None:
            await _post_approval_cards(state, approvals)

        decision = interrupt(
            {
                "kind": "mitigation_approval",
                "run_id": state["run_id"],
                "approvals": approvals,
            }
        )
        return {"approval_decision": dict(decision) if decision else None}

    async def _post_approval_cards(
        state: RunState, approvals: list[dict[str, str]]
    ) -> None:
        """Post one card per gated option (best effort; never fails the run)."""
        from flare.slack.blocks import mitigation_card

        drafts = {
            option_id: draft
            for option_id, draft in zip(
                state.get("pending_approvals", []),
                [d for d in state.get("mitigations", []) if d.approval_required],
                strict=False,
            )
        }
        for entry in approvals:
            draft = drafts.get(entry["option_id"])
            if draft is None or deps.approval_poster is None:
                continue
            try:
                await deps.approval_poster.post_approval(
                    blocks=mitigation_card(
                        approval_id=uuid.UUID(entry["approval_id"]),
                        title=draft.title,
                        description=draft.description,
                        risk=draft.risk,
                        reversibility=draft.reversibility,
                        expected_benefit=draft.expected_benefit,
                        dashboard_url=deps.dashboard_url,
                    ),
                    text=f"Approval needed: {draft.title}",
                )
            except Exception: 
                pass

    async def record_decision(state: RunState) -> RunState:
        decision = state.get("approval_decision") or {}
        if decision:
            await deps.recorder.add_limitation(
                f"mitigation {decision.get('decision', 'decided')} by a human "
                "(recorded as intent; not applied)"
            )
        return {}

    def route_after_gather(state: RunState) -> str:
        if state.get("verify_target"):
            return "verify"
        return "commit" if state.get("truncated") else "hypothesis"

    def route_mitigation(state: RunState) -> str:
        """Propose mitigations only when there is a cause to mitigate."""
        if not deps.mitigation.enabled:
            return "end"
        if state.get("truncated") or not state.get("hypotheses"):
            return "end"
        return "mitigate"

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
    g.add_node("verify", verify)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.add_node("revise", revise)
    g.add_node("commit_memory", commit_node)
    g.add_node("post_findings", post_findings)
    g.add_node("persist_run", persist_run)
    g.add_node("mitigate", mitigate)
    g.add_node("approval_gate", approval_gate)
    g.add_node("record_decision", record_decision)

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
        {
            "hypothesis": "hypothesis",
            "commit": "commit_memory",
            "verify": "verify",
        },
    )
    g.add_edge("verify", "persist_run")
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
    g.add_conditional_edges(
        "persist_run",
        route_mitigation,
        {"mitigate": "mitigate", "end": END},
    )
    g.add_edge("mitigate", "approval_gate")
    g.add_edge("approval_gate", "record_decision")
    g.add_edge("record_decision", END)

    return g.compile(checkpointer=MemorySaver())


def build_initial_graph(deps: GraphDeps):
    return build_investigation_graph(deps)

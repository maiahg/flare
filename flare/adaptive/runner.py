from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from flare.adaptive import supersede
from flare.adaptive.novelty import NoveltyVerdict
from flare.agents.planner import (
    AGENT_NAMES,
    InvestigationPlan,
    InvestigationPlannerAgent,
)
from flare.agents.schemas import ExtractedSignal
from flare.budgets import check_incident_budget
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.investigation.graph import (
    ApprovalPoster,
    GraphDeps,
    InvestigationPoster,
    RunSuperseded,
    build_investigation_graph,
)
from flare.investigation.recorder import RunRecorder
from flare.investigation.resume import capture_interrupt
from flare.investigation.state import RunState
from flare.llm import get_llm_client
from flare.models.claims import Hypothesis
from flare.redis import get_redis
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.adaptive")


def verdicts_from_context(trigger: dict[str, Any]) -> list[NoveltyVerdict]:
    """Rebuild novelty verdicts from a coalesced trigger payload."""
    verdicts: list[NoveltyVerdict] = []
    for entry in trigger.get("signals", []):
        signal_type = str(entry.get("type", ""))
        if not signal_type:
            continue
        verdicts.append(
            NoveltyVerdict(
                signal=ExtractedSignal(
                    signal_type=signal_type,
                    value={"text": str(entry.get("text", ""))},
                    confidence=float(entry.get("confidence", 0.9)),
                ),
                novel=bool(entry.get("novel", True)),
                category=str(entry.get("category", "other")),
                reason=str(entry.get("reason", "carried from triage")),
            )
        )
    return verdicts


async def leading_hypothesis(incident_id: uuid.UUID) -> str | None:
    """The incident's current top hypothesis, for the materiality bar"""
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(Hypothesis.statement)
            .where(
                Hypothesis.incident_id == incident_id,
                Hypothesis.status.notin_(("rejected", "superseded")),
            )
            .order_by(Hypothesis.likelihood.desc().nullslast())
            .limit(1)
        )


async def start_adaptive_run(
    incident_id: uuid.UUID,
    *,
    trigger: dict[str, Any] | None = None,
    created_by: str = "system",
    scenario: str = DEFAULT_SCENARIO,
    poster: InvestigationPoster | None = None,
    approval_poster: ApprovalPoster | None = None,
    dashboard_url: str = "",
    run_type: str = "adaptive",
    agents: Sequence[str] | None = None,
) -> uuid.UUID:
    """Plan and execute a targeted adaptive run; return the run id."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    redis = get_redis()
    trigger = trigger or {}
    verdicts = verdicts_from_context(trigger)

    recorder = RunRecorder(
        sessionmaker,
        incident_id=incident_id,
        run_type="run_type",
        trigger=trigger,
        created_by=created_by,
        scenario=scenario,
    )
    run_id = await recorder.start()
    await supersede.clear_supersede(redis, run_id)
    await supersede.register_run(redis, incident_id, run_id)

    verdict = await check_incident_budget(incident_id)
    if not verdict.allowed:
        _logger.warning(
            "incident %s is over its token budget; refusing an adaptive run",
            incident_id,
            extra={"used": verdict.used, "limit": verdict.limit},
        )
        await recorder.finish(
            status="cancelled", limitations=[verdict.limitation()], summary=None
        )
        return run_id

    if not dashboard_url:
        base = str(settings.app_base_url).rstrip("/")
        dashboard_url = f"{base}/incidents/{incident_id}"

    llm = get_llm_client()

    # ---- plan the targeted subgraph (its own trace, like any other agent)
    if agents is not None:
        plan = InvestigationPlan(
            agents=[name for name in agents if name in AGENT_NAMES],
            focus=str(trigger.get("focus") or "scheduled refresh"),
        )
        plan.checking = list(plan.agents)
    else:
        async with recorder.agent_step("InvestigationPlannerAgent", 0) as step:
            planner = InvestigationPlannerAgent(llm, model=settings.llm.models.planner)
            plan = await planner.run(verdicts=verdicts)
            step.output = {"agents": plan.agents, "focus": plan.focus}
            step.record_usage(planner.usage, fallback_model=settings.llm.models.planner)
    plan.service = plan.service or trigger.get("service")
    plan.suspect_service = plan.suspect_service or trigger.get("suspect_service")
    await recorder.save_plan(dict(plan.as_dict()))

    async def cancelled() -> bool:
        return await supersede.is_superseded(redis, run_id)

    deps = GraphDeps(
        llm=llm,
        recorder=recorder,
        sessionmaker=sessionmaker,
        models=settings.llm.models,
        budget=settings.run_budget,
        semaphore=asyncio.Semaphore(settings.run_budget.fan_out_concurrency),
        budget_started=time.monotonic(),
        dashboard_url=dashboard_url,
        poster=poster,
        cancelled=cancelled,
        mitigation=settings.mitigation,
        approval_poster=approval_poster,
    )
    graph = build_investigation_graph(deps, read_agents=plan.agents)

    initial_state: RunState = {
        "incident_id": str(incident_id),
        "run_id": str(run_id),
        "trigger": trigger,
        "plan": dict(plan.as_dict()),
        "evidence": [],
        "hypotheses": [],
        "limitations": [],
        "revision_count": 0,
    }

    config = {"configurable": {"thread_id": str(run_id)}}
    try:
        result = await graph.ainvoke(initial_state, config=config)
    except RunSuperseded:
        _logger.info("adaptive run %s superseded", run_id)
        await recorder.finish(
            status="superseded",
            limitations=["superseded by newer context"],
            summary=None,
        )
        return run_id
    except Exception:
        _logger.exception("adaptive run %s failed", run_id)
        await recorder.finish(status="failed", limitations=["run crashed"], summary=None)
        raise
    finally:
        await supersede.clear_run(redis, incident_id, run_id)
        await supersede.clear_supersede(redis, run_id)

    for _ in capture_interrupt(result, run_id, graph, config):
        await recorder.add_limitation("mitigation branch awaiting human approval")

    return run_id
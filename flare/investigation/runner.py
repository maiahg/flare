from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from flare.budgets import check_incident_budget
from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.investigation.graph import (
    ApprovalPoster,
    GraphDeps,
    InvestigationPoster,
    build_initial_graph,
)
from flare.investigation.recorder import BrokerFactory, RunRecorder
from flare.investigation.resume import capture_interrupt
from flare.investigation.state import RunState
from flare.llm import get_llm_client
from flare.tools.providers import resolve_default_service
from flare.tools.synthetic import DEFAULT_SCENARIO

_logger = logging.getLogger("flare.investigation")


async def start_initial_run(
    incident_id: uuid.UUID,
    *,
    trigger: dict[str, Any] | None = None,
    created_by: str = "system",
    scenario: str = DEFAULT_SCENARIO,
    poster: InvestigationPoster | None = None,
    approval_poster: ApprovalPoster | None = None,
    dashboard_url: str = "",
    broker_factory: BrokerFactory | None = None,
) -> uuid.UUID:
    """Run the initial investigation for an incident; return the run id."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    trigger = trigger or {}

    recorder = RunRecorder(
        sessionmaker,
        incident_id=incident_id,
        run_type="initial",
        trigger=trigger,
        created_by=created_by,
        scenario=scenario,
        broker_factory=broker_factory,
    )
    run_id = await recorder.start()

    verdict = await check_incident_budget(incident_id)
    if not verdict.allowed:
        _logger.warning(
            "incident %s is over its token budget; refusing the initial run",
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

    deps = GraphDeps(
        llm=get_llm_client(),
        recorder=recorder,
        sessionmaker=sessionmaker,
        models=settings.llm.models,
        budget=settings.run_budget,
        semaphore=asyncio.Semaphore(settings.run_budget.fan_out_concurrency),
        budget_started=time.monotonic(),
        dashboard_url=dashboard_url,
        poster=poster,
        mitigation=settings.mitigation,
        approval_poster=approval_poster,
        default_service=resolve_default_service(scenario),
    )
    graph = build_initial_graph(deps)

    initial_state: RunState = {
        "incident_id": str(incident_id),
        "run_id": str(run_id),
        "trigger": trigger,
        "evidence": [],
        "hypotheses": [],
        "limitations": [],
        "revision_count": 0,
    }

    config = {"configurable": {"thread_id": str(run_id)}}
    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception:
        _logger.exception("initial run %s failed", run_id)
        await recorder.finish(
            status="failed", limitations=["run crashed"], summary=None
        )
        raise

    for _ in capture_interrupt(result, run_id, graph, config):
        await recorder.add_limitation("mitigation branch awaiting human approval")

    return run_id
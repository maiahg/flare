from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from flare.config import get_settings
from flare.db.session import get_sessionmaker
from flare.investigation.graph import GraphDeps, InvestigationPoster, build_initial_graph
from flare.investigation.recorder import RunRecorder
from flare.investigation.state import RunState
from flare.llm import get_llm_client

_logger = logging.getLogger("flare.investigation")


async def start_initial_run(
    incident_id: uuid.UUID,
    *,
    trigger: dict[str, Any] | None = None,
    created_by: str = "system",
    scenario: str = "db_latency_spike",
    poster: InvestigationPoster | None = None,
    dashboard_url: str = "",
) -> uuid.UUID:
    """Run the initial investigation for an incident; return the run id.

    The run row is created up front (status=running) so tool-call FKs resolve;
    the graph's ``persist_run`` node flips it to ``done``. Any unexpected error
    marks the run ``failed`` and re-raises.
    """
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
    )
    run_id = await recorder.start()

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

    try:
        await graph.ainvoke(
            initial_state, config={"configurable": {"thread_id": str(run_id)}}
        )
    except Exception:
        _logger.exception("initial run %s failed", run_id)
        await recorder.finish(
            status="failed", limitations=["run crashed"], summary=None
        )
        raise

    return run_id
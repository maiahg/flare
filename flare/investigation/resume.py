from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.types import Command

_logger = logging.getLogger("flare.investigation.resume")

_PAUSED: dict[uuid.UUID, tuple[Any, dict[str, Any]]] = {}


def register_paused(run_id: uuid.UUID, graph: Any, config: dict[str, Any]) -> None:
    """Remember a run that stopped at an interrupt."""
    _PAUSED[run_id] = (graph, config)


def capture_interrupt(
    result: Any, run_id: uuid.UUID, graph: Any, config: dict[str, Any]
) -> list[Any]:
    """Register the run if the graph stopped at an interrupt; return the payloads."""
    interrupts = list((result or {}).get("__interrupt__") or [])
    if interrupts:
        register_paused(run_id, graph, config)
    return interrupts


def forget(run_id: uuid.UUID) -> None:
    _PAUSED.pop(run_id, None)


def is_paused(run_id: uuid.UUID) -> bool:
    return run_id in _PAUSED


async def resume_run(run_id: uuid.UUID, decision: dict[str, Any]) -> bool:
    """Resume a paused run with a human decision. True if it was resumed here."""
    entry = _PAUSED.pop(run_id, None)
    if entry is None:
        _logger.info(
            "no paused graph for run %s in this process; decision stands on its own",
            run_id,
        )
        return False
    graph, config = entry
    await graph.ainvoke(Command(resume=decision), config=config)
    _logger.info("resumed run %s after approval", run_id)
    return True
from __future__ import annotations

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flare.config import get_settings
from flare.tools.broker import ToolBroker
from flare.tools.specs import CATALOGUE_BY_NAME
from flare.tools.synthetic import DEFAULT_SCENARIO

logger = logging.getLogger(__name__)


def build_broker(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    incident_id: uuid.UUID,
    agent_trace_id: uuid.UUID | None = None,
    scenario: str = DEFAULT_SCENARIO,
    redis: Redis | None = None,
    provider: str | None = None,
) -> ToolBroker:
    """A broker loaded with the configured provider's adapters."""
    chosen = provider or get_settings().tools.provider
    broker = ToolBroker(
        session,
        run_id=run_id,
        incident_id=incident_id,
        agent_trace_id=agent_trace_id,
        redis=redis,
    )

    if chosen == "real":
        from flare.tools.real.provider import real_tools

        broker.register_all(real_tools())
    else:
        from flare.tools.synthetic.provider import load_scenario, synthetic_tools

        broker.register_all(synthetic_tools(load_scenario(scenario)))

    missing = set(CATALOGUE_BY_NAME) - broker.allowlist
    if missing:
        logger.warning(
            "provider %s registered no adapter for %s", chosen, sorted(missing)
        )
    return broker
from __future__ import annotations

from arq.connections import RedisSettings

from flare.config import get_settings
from flare.pipeline.adaptive import run_adaptive_investigation
from flare.pipeline.comms import generate_comms_draft
from flare.pipeline.investigation import run_initial_investigation
from flare.pipeline.messages import process_message
from flare.pipeline.postmortem import generate_postmortem_draft

def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


async def on_startup(ctx: dict) -> None:
    ctx["started"] = True


async def on_shutdown(ctx: dict) -> None:
    from flare.db.session import reset_engine
    await reset_engine()


class WorkerSettings:
    functions = [
        process_message,
        run_initial_investigation,
        run_adaptive_investigation,
        generate_comms_draft,
        generate_postmortem_draft,
    ]
    redis_settings = _redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 10
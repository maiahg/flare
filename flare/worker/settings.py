from __future__ import annotations

from arq.connections import RedisSettings

from flare.config import get_settings
from flare.pipeline.investigation import run_initial_investigation
from flare.pipeline.messages import process_message


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


async def on_startup(ctx: dict) -> None:
    ctx["started"] = True


async def on_shutdown(ctx: dict) -> None:
    from flare.db.session import reset_engine
    await reset_engine()


class WorkerSettings:
    functions = [process_message, run_initial_investigation]
    redis_settings = _redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 10
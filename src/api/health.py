from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from src.db.session import get_engine
from src.redis import get_redis

router = APIRouter(tags=["health"])

_logger = logging.getLogger("src.health")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is running and can serve requests."""
    return {"status": "ok"}


async def _check_database() -> bool:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        _logger.exception("database readiness check failed")
        return False


async def _check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        _logger.exception("redis readiness check failed")
        return False


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Readiness: dependencies (DB + Redis) are reachable."""
    database_ok = await _check_database()
    redis_ok = await _check_redis()
    ready = database_ok and redis_ok

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if ready else "unavailable",
        "checks": {"database": database_ok, "redis": redis_ok},
    }
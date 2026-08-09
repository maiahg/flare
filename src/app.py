from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api import v1
from src.api.health import router as health_router
from src.api.middleware import RequestIdMiddleware
from src.db.session import reset_engine
from src.logging import configure_logging
from src.redis import reset_redis

_logger = logging.getLogger("src.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage shared resources for the app's lifetime.

    The DB engine and Redis client are created lazily on first use, so startup
    is cheap; shutdown disposes both so connections are released cleanly.
    """
    _logger.info("application startup")
    try:
        yield
    finally:
        await reset_engine()
        await reset_redis()
        _logger.info("application shutdown")


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    configure_logging()

    app = FastAPI(
        title="flare",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)

    app.include_router(health_router)
    app.include_router(v1.router)

    return app


app = create_app()
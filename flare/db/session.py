from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from flare.config import get_settings

_enginge: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

def get_engine() -> AsyncEngine:
    """Get the global async SQLAlchemy engine, creating it if necessary."""
    global _enginge
    if _enginge is None:
        settings = get_settings()
        _enginge = create_async_engine(str(settings.database_url), pool_pre_ping=True,)
    return _enginge

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Get the global async SQLAlchemy sessionmaker, creating it if necessary."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a new async SQLAlchemy session."""
    async with get_sessionmaker()() as session:
        yield session

async def reset_engine() -> None:
    """Reset the global async SQLAlchemy engine and sessionmaker."""
    global _enginge, _sessionmaker
    if _enginge is not None:
        await _enginge.dispose()
    _enginge = None
    _sessionmaker = None
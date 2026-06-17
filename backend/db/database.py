"""Async SQLAlchemy setup for Meridian.

PostgreSQL runs on the host machine (not in Docker). The connection string is
built from environment variables via the shared Settings object.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# pool_pre_ping transparently recovers from connections dropped by the DB.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> bool:
    """Run a trivial query to verify the database is reachable.

    Called by the FastAPI lifespan handler on startup.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True

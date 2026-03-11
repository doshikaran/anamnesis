"""
Async SQLAlchemy 2.0 engine and session factory.
Connection pool (pool_size=20). No synchronous DB calls.
"""

from collections.abc import AsyncGenerator
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a single async session per request within a transaction."""
    async with async_session_factory() as session:
        async with session.begin():
            yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory for use in workers or UnitOfWork."""
    return async_session_factory

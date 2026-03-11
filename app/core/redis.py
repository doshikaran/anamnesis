"""
Redis connection pool. Used by Celery broker, cache, rate limiting, refresh tokens.
"""

from typing import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.config import get_settings

settings = get_settings()

_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    """Create or return existing connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency: yield a Redis connection from the pool."""
    pool = get_redis_pool()
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()


def get_sync_redis_url() -> str:
    """Return REDIS_URL for Celery (sync client)."""
    return settings.REDIS_URL

"""
Per-user rate limiting via Redis sliding window.
Phase 9: full implementation. Until then, stub that allows all requests.
"""

from typing import Any


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> bool:
    """
    Sliding window rate limit. Returns True if request is allowed, False if exceeded.
    Key is typically 'rl:{user_id}' or 'rl:query:{user_id}'.
    """
    try:
        from app.core.redis import get_redis_pool
        from redis.asyncio import Redis
        import time

        client = Redis(connection_pool=get_redis_pool())
        now = time.time()
        window_key = f"rate_limit:{key}"
        pipe = client.pipeline()
        pipe.zremrangebyscore(window_key, 0, now - window_seconds)
        pipe.zadd(window_key, {str(now): now})
        pipe.zcard(window_key)
        pipe.expire(window_key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
        await client.aclose()
        return count <= limit
    except Exception:
        return True  # Allow on Redis failure in development


def get_user_id_from_request(*args: Any, **kwargs: Any) -> Any:
    """Extract user_id from typical handler args/kwargs."""
    return kwargs.get("current_user") and getattr(kwargs["current_user"], "id", None) or kwargs.get("user_id")

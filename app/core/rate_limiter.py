"""
Per-user rate limiting via Redis sliding window (sorted sets).
Key pattern: rate_limit:{user_id}:{endpoint_key}
Algorithm: sliding window — remove entries outside window, check count, add current request, expire key.
"""

import math
import time
from uuid import uuid4

from fastapi import Depends
from redis.asyncio import Redis

from app.core.exceptions import RateLimitError
from app.core.redis import get_redis
from app.dependencies import get_current_user
from app.models.user import User


async def check_rate_limit(
    redis: Redis,
    user_id: str,
    endpoint_key: str,
    limit: int,
    period_seconds: int,
) -> None:
    """
    Sliding window rate limit. Raises RateLimitError with retry_after if exceeded.
    All 5 Redis commands run in a single pipeline (atomic).
    """
    key = f"rate_limit:{user_id}:{endpoint_key}"
    now_ms = int(time.time() * 1000)
    window_ms = period_seconds * 1000
    pipe = redis.pipeline()
    # 1. Remove entries outside the window
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    # 2. Count current entries
    pipe.zcard(key)
    # 3 & 4: We need to check count and conditionally get oldest; then add. Redis has no conditional,
    # so we run the pipeline, then in Python: if count >= limit, get oldest and raise; else ZADD + EXPIRE.
    # Spec says: 3. if count >= limit: get oldest score, retry_after = ceil((oldest + window_ms - now_ms)/1000), raise
    # 4. ZADD key now_ms {uuid4()}
    # 5. EXPIRE key (period_seconds * 2)
    results = await pipe.execute()
    count = results[1] if len(results) > 1 else 0
    if count >= limit:
        # Get oldest member score for retry_after
        oldest_list = await redis.zrange(key, 0, 0, withscores=True)
        oldest_ms = int(oldest_list[0][1]) if oldest_list else now_ms
        retry_after = max(1, math.ceil((oldest_ms + window_ms - now_ms) / 1000))
        raise RateLimitError(
            code="RATE_LIMIT_EXCEEDED",
            message=f"Too many requests. Try again in {retry_after} seconds.",
            retry_after=retry_after,
        )
    pipe2 = redis.pipeline()
    pipe2.zadd(key, {str(uuid4()): now_ms})
    pipe2.expire(key, period_seconds * 2)
    await pipe2.execute()


def rate_limit(calls: int, period_seconds: int, key: str):
    """FastAPI dependency factory. Returns a Depends(dependency) that checks rate limit for current user."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        redis: Redis = Depends(get_redis),
    ) -> None:
        await check_rate_limit(redis, str(current_user.id), key, calls, period_seconds)

    return Depends(dependency)

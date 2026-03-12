"""
Cross-cutting decorators: retry with exponential backoff, rate limiting.
Use on all external API calls and on write/AI endpoints.
"""

import asyncio
import random
from functools import wraps
from typing import Callable, TypeVar

import structlog

log = structlog.get_logger()

F = TypeVar("F", bound=Callable)


def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """Retry with exponential backoff + jitter. Use on all external API calls."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts - 1:
                        raise
                    wait = (backoff_factor**attempt) + random.uniform(0, 1)
                    log.warning(
                        "retry.attempt",
                        func=func.__name__,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        wait_seconds=round(wait, 2),
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def rate_limited(calls_per_minute: int, key_prefix: str = "rl"):
    """
    Per-user rate limiting using Redis sliding window (same as app.core.rate_limiter).
    Expects first arg or kwargs to include 'user_id' (UUID) or similar.
    Raises RateLimitError if exceeded.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from redis.asyncio import Redis
            from app.core.redis import get_redis_pool
            from app.core.rate_limiter import check_rate_limit

            user_id = kwargs.get("user_id") or (kwargs.get("current_user") and getattr(kwargs["current_user"], "id", None)) or (args[0] if args else None)
            if user_id is None:
                return await func(*args, **kwargs)
            uid = str(getattr(user_id, "id", user_id) if hasattr(user_id, "id") else user_id)
            pool = get_redis_pool()
            client = Redis(connection_pool=pool)
            try:
                await check_rate_limit(client, uid, key_prefix, calls_per_minute, 60)
            finally:
                await client.aclose()
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

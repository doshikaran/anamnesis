"""
JWT creation and validation. Access tokens 15 min, refresh 30 days.
Refresh token rotation via Redis (store refresh token with user_id, rotate on use).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from redis.asyncio import Redis

from app.config import get_settings
from app.core.exceptions import UnauthorizedError

settings = get_settings()

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30
ALGORITHM = "HS256"
REFRESH_PREFIX = "refresh:"


def create_access_token(sub: str) -> str:
    """Create JWT access token. sub = user id (UUID string)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": sub, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(sub: str) -> str:
    """Create JWT refresh token (long-lived). Store in Redis on use."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": sub, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate JWT. Raises UnauthorizedError if invalid."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise UnauthorizedError(code="INVALID_TOKEN", message="Invalid or expired token")


async def store_refresh_token(redis: Redis, user_id: UUID, refresh_token: str) -> None:
    """Store refresh token in Redis with TTL. Key: refresh:{user_id} (or token hash)."""
    key = f"{REFRESH_PREFIX}{user_id}"
    ttl = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    await redis.setex(key, ttl, refresh_token)


async def get_stored_refresh_token(redis: Redis, user_id: UUID) -> str | None:
    """Return stored refresh token for user if any."""
    key = f"{REFRESH_PREFIX}{user_id}"
    return await redis.get(key)


async def rotate_refresh_token(redis: Redis, user_id: UUID, old_token: str, new_token: str) -> None:
    """Invalidate old token and store new one (rotation)."""
    key = f"{REFRESH_PREFIX}{user_id}"
    current = await redis.get(key)
    if current != old_token:
        raise UnauthorizedError(code="REFRESH_TOKEN_REUSED", message="Refresh token was already used")
    ttl = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    await redis.setex(key, ttl, new_token)


async def revoke_refresh_token(redis: Redis, user_id: UUID) -> None:
    """Remove refresh token on logout."""
    key = f"{REFRESH_PREFIX}{user_id}"
    await redis.delete(key)

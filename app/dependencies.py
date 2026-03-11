"""
FastAPI dependency injection. get_db, get_redis, get_current_user, repository and service dependencies.
No global state. All dependencies use Depends().
"""

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedError
from app.repositories.user_repository import UserRepository
from app.models.user import User

# Prefer Bearer token for API; OAuth2PasswordBearer for OpenAPI doc
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/refresh", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve JWT to User. Raise UnauthorizedError if invalid or user deleted."""
    if not credentials:
        raise UnauthorizedError(code="MISSING_TOKEN", message="Authorization header required")
    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise UnauthorizedError(code="INVALID_TOKEN", message="Access token required")
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError(code="INVALID_TOKEN", message="Missing sub")
    try:
        user_id = UUID(sub)
    except ValueError:
        raise UnauthorizedError(code="INVALID_TOKEN", message="Invalid user id")
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(user_id)
    if not user:
        raise UnauthorizedError(code="INVALID_TOKEN", message="User not found or deleted")
    return user


# Repository dependencies
def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db, User)


# Optional: get_commitment_service, get_people_service, etc. added in later phases

"""
Auth service: OAuth callbacks (Google, Microsoft), create/update user, refresh token, logout.
Uses repositories only. Encrypts tokens before saving to DB.
Saves connection tokens (encrypted) after OAuth for data-source connections.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.core.encryption import encrypt_token
from app.core.exceptions import UnauthorizedError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    rotate_refresh_token,
    revoke_refresh_token,
    store_refresh_token,
)
from app.repositories.user_repository import UserRepository
from app.repositories.connection_repository import ConnectionRepository
from app.models.user import User
from app.models.connection import Connection
from app.schemas.auth import TokenResponse, UserResponse


async def handle_google_callback(
    db: AsyncSession,
    redis: Redis,
    *,
    code: str,
    state: str | None = None,
    redirect_uri: str | None = None,
) -> TokenResponse:
    """Exchange Google OAuth code for tokens, create/update user, return JWT."""
    from app.config import get_settings
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    import httpx

    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ValidationError(code="OAUTH_NOT_CONFIGURED", message="Google OAuth not configured")
    if not redirect_uri:
        redirect_uri = f"{settings.FRONTEND_URL.rstrip('/')}/api/auth/google/callback"
    async with AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=redirect_uri,
    ) as client:
        token = await client.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
        )
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            )
            resp.raise_for_status()
            userinfo = resp.json()
    google_id = userinfo.get("id")
    email = userinfo.get("email")
    if not google_id or not email:
        raise ValidationError(code="OAUTH_MISSING_FIELDS", message="Google did not return id or email")
    user = await get_or_create_user_by_google(
        db,
        google_id=google_id,
        email=email,
        full_name=userinfo.get("name"),
        avatar_url=userinfo.get("picture"),
    )
    await db.flush()
    sub = str(user.id)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    await store_refresh_token(redis, user.id, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


async def handle_microsoft_callback(
    db: AsyncSession,
    redis: Redis,
    *,
    code: str,
    state: str | None,
) -> TokenResponse:
    """Exchange Microsoft OAuth code for tokens, create/update user, return JWT."""
    # TODO Phase 2: use msal to exchange code and get user info
    raise ValidationError(
        code="NOT_IMPLEMENTED",
        message="Microsoft OAuth callback not yet implemented; configure msal and credentials",
    )


async def save_connection_tokens(
    db: AsyncSession,
    user_id: UUID,
    *,
    source_type: str,
    access_token: str,
    refresh_token: str,
    token_expires_at=None,
    scopes: list[str] | None = None,
    display_name: str | None = None,
) -> Connection:
    """
    Save or update OAuth tokens for a data-source connection.
    Encrypts tokens before storing. Creates connection if not exists.
    """
    access_encrypted = encrypt_token(user_id, access_token)
    refresh_encrypted = encrypt_token(user_id, refresh_token)
    repo = ConnectionRepository(db, Connection)
    existing = await repo.get_by_user_and_source_type(user_id, source_type)
    if existing:
        await repo.update(
            existing,
            access_token=access_encrypted,
            refresh_token=refresh_encrypted,
            token_expires_at=token_expires_at,
            scopes=scopes,
            display_name=display_name or existing.display_name,
            status="active",
            last_error=None,
            error_count=0,
        )
        await db.flush()
        return existing
    return await repo.create(
        user_id=user_id,
        source_type=source_type,
        access_token=access_encrypted,
        refresh_token=refresh_encrypted,
        token_expires_at=token_expires_at,
        scopes=scopes,
        display_name=display_name,
        status="active",
    )


async def get_or_create_user_by_google(
    db: AsyncSession,
    google_id: str,
    email: str,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Get existing user by google_id or create new one."""
    repo = UserRepository(db, User)
    existing = await repo.get_by_google_id(google_id)
    if existing:
        await repo.update(existing, full_name=full_name or existing.full_name, avatar_url=avatar_url or existing.avatar_url)
        return existing
    existing_email = await repo.get_by_email(email)
    if existing_email:
        await repo.update(existing_email, google_id=google_id, full_name=full_name or existing_email.full_name, avatar_url=avatar_url or existing_email.avatar_url)
        return existing_email
    return await repo.create(
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        google_id=google_id,
        auth_provider="google",
    )


async def get_or_create_user_by_microsoft(
    db: AsyncSession,
    microsoft_id: str,
    email: str,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Get existing user by microsoft_id or create new one."""
    repo = UserRepository(db, User)
    existing = await repo.get_by_microsoft_id(microsoft_id)
    if existing:
        await repo.update(existing, full_name=full_name or existing.full_name, avatar_url=avatar_url or existing.avatar_url)
        return existing
    existing_email = await repo.get_by_email(email)
    if existing_email:
        await repo.update(existing_email, microsoft_id=microsoft_id, full_name=full_name or existing_email.full_name, avatar_url=avatar_url or existing_email.avatar_url)
        return existing_email
    return await repo.create(
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        microsoft_id=microsoft_id,
        auth_provider="microsoft",
    )


async def refresh_access_token(redis: Redis, db: AsyncSession, refresh_token: str) -> TokenResponse:
    """Validate refresh token, rotate it, return new access + refresh."""
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise UnauthorizedError(code="INVALID_TOKEN", message="Not a refresh token")
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError(code="INVALID_TOKEN", message="Missing sub")
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(UUID(sub))
    if not user:
        raise UnauthorizedError(code="USER_NOT_FOUND", message="User not found")
    new_refresh = create_refresh_token(sub)
    await rotate_refresh_token(redis, user.id, refresh_token, new_refresh)
    return TokenResponse(
        access_token=create_access_token(sub),
        refresh_token=new_refresh,
    )


async def logout(redis: Redis, user_id: UUID) -> None:
    """Invalidate refresh token for user."""
    await revoke_refresh_token(redis, user_id)


def user_to_response(user: User) -> UserResponse:
    """Map User ORM to UserResponse schema."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        auth_provider=user.auth_provider,
        timezone=user.timezone,
        onboarding_complete=user.onboarding_complete,
        plan=user.plan,
    )

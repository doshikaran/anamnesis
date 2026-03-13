"""
Auth API: /auth/* — Google OAuth, Microsoft OAuth, refresh, logout, /auth/me.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_current_user, get_db, get_redis
from app.models.user import User
from app.schemas.auth import TokenResponse, UserResponse, RefreshRequest
from app.services.auth_service import (
    handle_google_callback,
    handle_microsoft_callback,
    refresh_access_token,
    logout,
    user_to_response,
)

router = APIRouter()
log = structlog.get_logger()
settings = get_settings()


@router.get("/google/login")
async def auth_google_login(request: Request):
    """Initiate Google OAuth flow. Redirects to Google consent screen."""
    import base64
    import json

    # Redirect URI: backend URL for callback (Google will send code here)
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/auth/google/callback"
    state = base64.urlsafe_b64encode(json.dumps({"provider": "google", "redirect_uri": redirect_uri}).encode()).decode()
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        "?client_id={}&redirect_uri={}&response_type=code&scope=openid%20email%20profile&state={}&access_type=offline&prompt=consent"
    ).format(settings.GOOGLE_CLIENT_ID, redirect_uri, state)
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def auth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Handle Google OAuth callback. Exchange code for tokens, create/update user, return JWT."""
    if error:
        log.warning("auth.google_callback_error", error=error)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error={error}")
    if not code:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error=missing_code")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/auth/google/callback"
    try:
        result = await handle_google_callback(db, redis, code=code, state=state, redirect_uri=redirect_uri)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/callback/google?access_token={result.access_token}&refresh_token={result.refresh_token}")
    except Exception as e:
        log.exception("auth.google_callback_failed", error=str(e))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error=callback_failed")


@router.get("/microsoft/login")
async def auth_microsoft_login(request: Request):
    """Initiate Microsoft OAuth flow."""
    import base64
    import json
    redirect_uri = str(request.base_url).rstrip("/") + "/api/auth/microsoft/callback"
    state = base64.urlsafe_b64encode(json.dumps({"provider": "microsoft", "redirect_uri": redirect_uri}).encode()).decode()
    url = (
        f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
        f"?client_id={settings.MICROSOFT_CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}&scope=openid%20email%20profile%20offline_access&state={state}"
    )
    return RedirectResponse(url=url)


@router.get("/microsoft/callback")
async def auth_microsoft_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Handle Microsoft OAuth callback."""
    if error:
        log.warning("auth.microsoft_callback_error", error=error)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error={error}")
    if not code:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error=missing_code")
    try:
        result = await handle_microsoft_callback(db, redis, code=code, state=state)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/callback/microsoft?access_token={result.access_token}&refresh_token={result.refresh_token}")
    except Exception as e:
        log.exception("auth.microsoft_callback_failed", error=str(e))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/error?error=callback_failed")


@router.post("/refresh", response_model=TokenResponse)
async def auth_refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Refresh access token using refresh token. Rotates refresh token."""
    return await refresh_access_token(redis, db, body.refresh_token)


@router.post("/logout")
async def auth_logout(
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
):
    """Invalidate refresh token for current user."""
    await logout(redis, current_user.id)
    return {"success": True}


@router.get("/me", response_model=UserResponse)
async def auth_me(current_user: User = Depends(get_current_user)):
    """Get current user (protected)."""
    log.info("auth.me", user_id=str(current_user.id))
    return user_to_response(current_user)

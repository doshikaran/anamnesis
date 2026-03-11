"""
Users API: /users/* — profile, preferences, push subscription, data export, account deletion.
"""

import structlog
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_redis
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserProfileSchema, UserUpdateSchema, PushSubscriptionSchema
from app.core.exceptions import NotFoundError

router = APIRouter()
log = structlog.get_logger()


def _user_to_profile(user: User) -> UserProfileSchema:
    return UserProfileSchema(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        auth_provider=user.auth_provider,
        timezone=user.timezone,
        briefing_time=user.briefing_time.strftime("%H:%M") if user.briefing_time else "08:00",
        briefing_enabled=user.briefing_enabled,
        nudge_max_per_day=user.nudge_max_per_day,
        language=user.language,
        onboarding_complete=user.onboarding_complete,
        onboarding_step=user.onboarding_step,
        plan=user.plan,
        push_enabled=user.push_enabled or False,
    )


@router.get("/me", response_model=UserProfileSchema)
async def users_me(current_user: User = Depends(get_current_user)):
    """Full user profile (protected)."""
    log.info("users.me", user_id=str(current_user.id))
    return _user_to_profile(current_user)


@router.patch("/me", response_model=UserProfileSchema)
async def users_me_update(
    body: UserUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update preferences, timezone, name (protected)."""
    log.info("users.me_update", user_id=str(current_user.id))
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(current_user.id)
    if not user:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    updates = body.model_dump(exclude_unset=True)
    if "briefing_time" in updates and isinstance(updates["briefing_time"], str):
        from datetime import time
        parts = updates["briefing_time"].split(":")
        updates["briefing_time"] = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
    await repo.update(user, **updates)
    await db.refresh(user)
    return _user_to_profile(user)


@router.get("/me/stats")
async def users_me_stats(current_user: User = Depends(get_current_user)):
    """Usage stats, plan limits (protected). Placeholder for Phase 5 usage_service."""
    return {"plan": current_user.plan, "usage": {}}


@router.post("/me/push-subscription")
async def users_me_push_subscription(
    body: PushSubscriptionSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register PWA push subscription (protected)."""
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(current_user.id)
    if not user:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    keys = body.keys or {}
    await repo.update(
        user,
        push_endpoint=body.endpoint,
        push_p256dh=keys.get("p256dh"),
        push_auth=keys.get("auth"),
        push_enabled=True,
    )
    return {"success": True}


@router.delete("/me/push-subscription")
async def users_me_push_subscription_remove(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove push subscription (protected)."""
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(current_user.id)
    if not user:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    await repo.update(user, push_endpoint=None, push_p256dh=None, push_auth=None, push_enabled=False)
    return {"success": True}


@router.post("/me/export")
async def users_me_export(current_user: User = Depends(get_current_user)):
    """Request data export → S3 download (protected). Placeholder for Phase 9."""
    log.info("users.export_requested", user_id=str(current_user.id))
    return {"message": "Export requested. You will receive a link when ready."}


@router.delete("/me")
async def users_me_delete(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request account deletion (protected). Soft-delete; cascade handled by DB."""
    repo = UserRepository(db, User)
    user = await repo.get_by_id_active(current_user.id)
    if not user:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    from datetime import datetime, timezone
    await repo.update(user, delete_requested_at=datetime.now(timezone.utc))
    log.info("users.delete_requested", user_id=str(current_user.id))
    return {"success": True, "message": "Account deletion requested."}

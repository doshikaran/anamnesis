"""User request/response schemas."""

from datetime import time
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserProfileSchema(BaseModel):
    """Full user profile (GET /users/me)."""
    id: str
    email: str
    full_name: str | None
    avatar_url: str | None
    auth_provider: str
    timezone: str
    briefing_time: str  # HH:MM
    briefing_enabled: bool
    nudge_max_per_day: int
    language: str
    onboarding_complete: bool
    onboarding_step: str | None
    plan: str
    push_enabled: bool

    class Config:
        from_attributes = True


class UserUpdateSchema(BaseModel):
    """PATCH /users/me body."""
    full_name: str | None = None
    timezone: str | None = None
    briefing_time: str | None = None  # HH:MM
    briefing_enabled: bool | None = None
    nudge_max_per_day: int | None = None
    language: str | None = None


class PushSubscriptionSchema(BaseModel):
    """PWA push subscription (POST /users/me/push-subscription)."""
    endpoint: str
    keys: dict  # {"p256dh": "...", "auth": "..."}

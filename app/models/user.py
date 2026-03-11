"""User model. Maps to users table."""

from datetime import datetime, time
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    google_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    microsoft_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False, default="google")
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    briefing_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(8, 0, 0))
    briefing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    nudge_max_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en")
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_step: Mapped[Optional[str]] = mapped_column(Text, default="connect_first_source")
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    stripe_sub_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    encryption_key_id: Mapped[Optional[str]] = mapped_column(Text)
    data_export_token: Mapped[Optional[str]] = mapped_column(Text)
    delete_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    push_endpoint: Mapped[Optional[str]] = mapped_column(Text)
    push_p256dh: Mapped[Optional[str]] = mapped_column(Text)
    push_auth: Mapped[Optional[str]] = mapped_column(Text)
    push_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

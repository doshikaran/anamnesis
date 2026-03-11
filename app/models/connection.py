"""Connection model. Maps to connections table."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Connection(Base, TimestampMixin):
    __tablename__ = "connections"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    microsoft_tenant_id: Mapped[Optional[str]] = mapped_column(Text)
    slack_team_id: Mapped[Optional[str]] = mapped_column(Text)
    slack_team_name: Mapped[Optional[str]] = mapped_column(Text)
    slack_bot_token: Mapped[Optional[str]] = mapped_column(Text)
    slack_user_token: Mapped[Optional[str]] = mapped_column(Text)
    bridge_webhook_secret: Mapped[Optional[str]] = mapped_column(Text)
    bridge_last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notion_workspace_id: Mapped[Optional[str]] = mapped_column(Text)
    notion_workspace_name: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    error_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    sync_cursor: Mapped[Optional[str]] = mapped_column(Text)
    sync_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    sync_from_date: Mapped[Optional[date]] = mapped_column(Date)
    sync_frequency_mins: Mapped[Optional[int]] = mapped_column(Integer, default=30)
    display_name: Mapped[Optional[str]] = mapped_column(Text)

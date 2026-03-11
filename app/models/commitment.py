"""Commitment model. Maps to commitments table."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Commitment(Base, TimestampMixin):
    __tablename__ = "commitments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    commitment_type: Mapped[str] = mapped_column(Text, nullable=False, default="promise")
    direction: Mapped[str] = mapped_column(Text, nullable=False, default="outbound")
    person_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL"))
    person_name_raw: Mapped[Optional[str]] = mapped_column(Text)
    source_message_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"))
    source_thread_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL"))
    source_type: Mapped[Optional[str]] = mapped_column(Text)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deadline_raw: Mapped[Optional[str]] = mapped_column(Text)
    deadline_type: Mapped[Optional[str]] = mapped_column(Text)
    deadline_confidence: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismissed_reason: Mapped[Optional[str]] = mapped_column(Text)
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)
    is_verified: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    urgency_score: Mapped[Optional[float]] = mapped_column(Float, default=0.5)
    priority: Mapped[Optional[str]] = mapped_column(Text, default="medium")
    nudge_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_nudged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_nudge_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

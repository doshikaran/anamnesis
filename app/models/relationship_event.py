"""RelationshipEvent model. Maps to relationship_events table."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RelationshipEvent(Base):
    __tablename__ = "relationship_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    person_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    source_message_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[Optional[date]] = mapped_column(Date)
    event_date_approx: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=0.9)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    requires_followup: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    followup_done: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    followup_due_at: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

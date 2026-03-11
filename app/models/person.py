"""Person model. Maps to people table."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin


class Person(Base, TimestampMixin):
    __tablename__ = "people"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(Text)
    last_name: Mapped[Optional[str]] = mapped_column(Text)
    canonical_email: Mapped[Optional[str]] = mapped_column(Text)
    all_emails: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    phone_numbers: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False, default="contact")
    relationship_label: Mapped[Optional[str]] = mapped_column(Text)
    importance_score: Mapped[Optional[float]] = mapped_column(Float, default=0.5)
    is_starred: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    avg_response_days: Mapped[Optional[float]] = mapped_column(Float)
    contact_frequency: Mapped[Optional[str]] = mapped_column(Text)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    sentiment_trend: Mapped[Optional[str]] = mapped_column(Text)
    sentiment_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    known_facts: Mapped[Optional[list]] = mapped_column(JSONB, default="[]")
    life_events: Mapped[Optional[list]] = mapped_column(JSONB, default="[]")
    open_topics: Mapped[Optional[list]] = mapped_column(JSONB, default="[]")
    sources: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    external_ids: Mapped[Optional[dict]] = mapped_column(JSONB, default="{}")
    merged_from: Mapped[Optional[list[UUID]]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    is_merged: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536))
    last_analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

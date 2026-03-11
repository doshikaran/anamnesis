"""Message model. Maps to messages table."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connections.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(Text)
    thread_id: Mapped[Optional[str]] = mapped_column(Text)
    db_thread_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL"))
    sender_person_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("people.id", ondelete="SET NULL"))
    sender_raw: Mapped[Optional[str]] = mapped_column(Text)
    recipient_person_ids: Mapped[Optional[list[UUID]]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    recipients_raw: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    body_raw: Mapped[Optional[str]] = mapped_column(Text)
    body_clean: Mapped[Optional[str]] = mapped_column(Text)
    body_summary: Mapped[Optional[str]] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    audio_s3_key: Mapped[Optional[str]] = mapped_column(Text)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    sentiment_label: Mapped[Optional[str]] = mapped_column(Text)
    topics: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    entities_mentioned: Mapped[Optional[list]] = mapped_column(JSONB, default="[]")
    has_commitment: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    has_question: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    importance_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    content_hash: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

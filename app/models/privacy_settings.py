"""PrivacySettings model. Maps to privacy_settings table."""

from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PrivacySettings(Base, TimestampMixin):
    __tablename__ = "privacy_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    excluded_person_ids: Mapped[Optional[list[UUID]]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), default="{}")
    excluded_sources: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), default="{}")
    excluded_emails: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), default="{}")
    allow_sentiment: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    allow_pattern_detection: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    allow_relationship_scoring: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    message_retention_days: Mapped[Optional[int]] = mapped_column(Integer, default=365)
    delete_raw_after_analysis: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

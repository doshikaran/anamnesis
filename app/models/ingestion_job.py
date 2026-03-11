"""IngestionJob model. Maps to ingestion_jobs table."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    total_items: Mapped[Optional[int]] = mapped_column(Integer)
    processed_items: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    failed_items: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    progress_pct: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    items_created: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    items_updated: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    items_skipped: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    error_log: Mapped[Optional[list]] = mapped_column(JSONB, default="[]")
    celery_task_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

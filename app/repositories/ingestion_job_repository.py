"""Ingestion job repository. All ingestion_jobs data access."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_job import IngestionJob
from app.repositories.base import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJob]):
    def __init__(self, session: AsyncSession, model: type[IngestionJob] = IngestionJob):
        super().__init__(session, model)

    async def list_by_connection(self, connection_id: UUID, limit: int = 20) -> list[IngestionJob]:
        result = await self.session.execute(
            select(IngestionJob)
            .where(IngestionJob.connection_id == connection_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user(self, user_id: UUID, limit: int = 50) -> list[IngestionJob]:
        result = await self.session.execute(
            select(IngestionJob)
            .where(IngestionJob.user_id == user_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> IngestionJob | None:
        result = await self.session.execute(
            select(IngestionJob).where(IngestionJob.id == id, IngestionJob.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def set_started(self, job: IngestionJob, celery_task_id: str | None = None) -> IngestionJob:
        now = datetime.now(timezone.utc)
        await self.update(
            job,
            status="running",
            started_at=now,
            celery_task_id=celery_task_id,
        )
        return job

    async def set_completed(
        self,
        job: IngestionJob,
        *,
        items_created: int = 0,
        items_updated: int = 0,
        items_skipped: int = 0,
        duration_ms: int | None = None,
    ) -> IngestionJob:
        now = datetime.now(timezone.utc)
        total = (items_created or 0) + (items_updated or 0) + (items_skipped or 0)
        progress = 100.0 if total else 0.0
        await self.update(
            job,
            status="completed",
            completed_at=now,
            processed_items=total,
            progress_pct=progress,
            items_created=items_created,
            items_updated=items_updated,
            items_skipped=items_skipped,
            duration_ms=duration_ms,
        )
        return job

    async def set_failed(self, job: IngestionJob, error_message: str) -> IngestionJob:
        now = datetime.now(timezone.utc)
        error_log = list(job.error_log or [])
        error_log.append({"at": now.isoformat(), "message": error_message})
        await self.update(
            job,
            status="failed",
            completed_at=now,
            last_error=error_message,
            error_log=error_log,
        )
        return job

    async def append_error_log(self, job: IngestionJob, message: str) -> IngestionJob:
        now = datetime.now(timezone.utc)
        error_log = list(job.error_log or [])
        error_log.append({"at": now.isoformat(), "message": message})
        await self.update(job, error_log=error_log)
        return job

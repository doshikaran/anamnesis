"""
Sync tasks: sync a single connection (full or incremental), sync all active connections.
Idempotent: re-running same job is safe (dedup by external_id).
"""

import asyncio
import time
from uuid import UUID

import structlog

from app.core.database import get_session_factory
from app.core.unit_of_work import UnitOfWork
from app.core.encryption import decrypt_token
from app.core.exceptions import ValidationError
from app.ingestion import get_connector
from app.utils.datetime_utils import utcnow
from app.workers.celery_app import celery_app

log = structlog.get_logger()


async def _run_sync_connection(
    connection_id_str: str,
    job_type: str = "full_sync",
    celery_task_id: str | None = None,
) -> None:
    """Async body: load connection, create job, run connector, update job and connection."""
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        connection_id = UUID(connection_id_str)
        conn = await uow.connections.get_by_id(connection_id)
        if not conn:
            log.warning("sync.connection_not_found", connection_id=connection_id_str)
            return
        if conn.status not in ("active", "pending"):
            log.warning("sync.connection_not_active", connection_id=connection_id_str, status=conn.status)
            return
        try:
            decrypted_access = decrypt_token(conn.user_id, conn.access_token or "")
            decrypted_refresh = decrypt_token(conn.user_id, conn.refresh_token or "")
        except Exception as e:
            log.warning("sync.decrypt_failed", connection_id=connection_id_str, error=str(e))
            return
        connector = get_connector(conn, decrypted_access, decrypted_refresh)
        job = await uow.ingestion_jobs.create(
            user_id=conn.user_id,
            connection_id=conn.id,
            job_type=job_type,
            status="queued",
        )
        await uow.ingestion_jobs.set_started(job, celery_task_id=celery_task_id)
        started = time.monotonic()
        try:
            if job_type == "full_sync":
                result = await connector.full_sync(job.id, uow=uow)
            else:
                result = await connector.incremental_sync(job.id, uow=uow)
            duration_ms = int((time.monotonic() - started) * 1000)
            await uow.ingestion_jobs.set_completed(
                job,
                items_created=result.created,
                items_updated=result.updated,
                items_skipped=result.skipped,
                duration_ms=duration_ms,
            )
            await uow.connections.update(
                conn,
                last_synced_at=utcnow(),
                last_error=None,
                error_count=0,
            )
            if result.errors:
                for err in result.errors:
                    await uow.ingestion_jobs.append_error_log(job, err)
            log.info(
                "sync.completed",
                connection_id=connection_id_str,
                job_id=str(job.id),
                created=result.created,
                updated=result.updated,
                skipped=result.skipped,
                duration_ms=duration_ms,
            )
        except Exception as e:
            await uow.ingestion_jobs.set_failed(job, str(e))
            await uow.connections.update(
                conn,
                last_error=str(e)[:500],
                error_count=(conn.error_count or 0) + 1,
            )
            log.exception("sync.failed", connection_id=connection_id_str, job_id=str(job.id), error=str(e))
            raise


@celery_app.task(bind=True, max_retries=3)
def sync_connection(self, connection_id: str, job_type: str = "full_sync"):
    """
    Sync a single connection. job_type: 'full_sync' | 'incremental'.
    Idempotent: messages deduplicated by external_id.
    """
    log.info("sync_connection.started", connection_id=connection_id, job_type=job_type)
    try:
        asyncio.run(_run_sync_connection(connection_id, job_type, celery_task_id=self.request.id))
    except Exception as e:
        log.exception("sync_connection.error", connection_id=connection_id, error=str(e))
        raise self.retry(exc=e)


async def _run_sync_all_active() -> None:
    """List all active+sync_enabled connections and queue a sync task for each."""
    from app.workers.sync_tasks import sync_connection

    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        connections = await uow.connections.list_active_for_sync()
    for conn in connections:
        sync_connection.delay(str(conn.id), job_type="incremental")
    log.info("sync_all.queued", count=len(connections))


@celery_app.task(bind=True)
def sync_all_active_connections(self):
    """Beat task: every 30 min, queue incremental sync for all active connections."""
    log.info("sync_all_active_connections.started")
    asyncio.run(_run_sync_all_active())

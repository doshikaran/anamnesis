"""
Maintenance tasks: merge duplicate people, enforce data retention.
Runs nightly via Celery beat.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog

from app.core.database import get_session_factory
from app.core.unit_of_work import UnitOfWork
from app.services.people_service import merge_people
from app.workers.celery_app import celery_app

log = structlog.get_logger()

# Auto-merge when similarity above this; below threshold we could queue for review
MERGE_AUTO_THRESHOLD = 0.95


async def _run_find_and_merge_duplicates() -> None:
    """Find merge candidates and auto-merge high-confidence pairs."""
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        # Get all distinct user_ids that have people
        from sqlalchemy import select, distinct
        from app.models.person import Person

        result = await uow.session.execute(select(distinct(Person.user_id)))
        user_ids = [row[0] for row in result.fetchall()]
    for user_id in user_ids:
        async with UnitOfWork(factory) as uow:
            candidates = await uow.people.find_merge_candidates(user_id, similarity_threshold=0.5)
            for person_a, person_b, similarity in candidates:
                if similarity >= MERGE_AUTO_THRESHOLD:
                    try:
                        await merge_people(uow, user_id, person_a.id, person_b.id)
                        log.info(
                            "maintenance.merged_duplicates",
                            user_id=str(user_id),
                            primary_id=str(person_a.id),
                            secondary_id=str(person_b.id),
                            similarity=round(similarity, 3),
                        )
                    except Exception as e:
                        log.warning(
                            "maintenance.merge_failed",
                            user_id=str(user_id),
                            a_id=str(person_a.id),
                            b_id=str(person_b.id),
                            error=str(e),
                        )


@celery_app.task(bind=True)
def find_and_merge_duplicates(self):
    """Nightly: find duplicate people (trigram similarity) and auto-merge high-confidence pairs."""
    log.info("maintenance.find_and_merge_duplicates.started")
    asyncio.run(_run_find_and_merge_duplicates())


async def _run_enforce_data_retention() -> None:
    """Soft-delete messages older than user's message_retention_days."""
    from sqlalchemy import select, update
    from app.models.message import Message
    from app.models.privacy_settings import PrivacySettings
    from app.models.user import User

    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    # Build user_id -> retention_days (default 365)
    async with UnitOfWork(factory) as uow:
        result = await uow.session.execute(select(PrivacySettings))
        settings_list = result.scalars().all()
        result2 = await uow.session.execute(select(User.id).where(User.deleted_at.is_(None)))
        all_user_ids = [r[0] for r in result2.fetchall()]
    retention_by_user = {ps.user_id: (ps.message_retention_days or 365) for ps in settings_list}
    for user_id in all_user_ids:
        days = retention_by_user.get(user_id, 365)
        cutoff = now - timedelta(days=days)
        async with UnitOfWork(factory) as uow:
            await uow.session.execute(
                update(Message).where(
                    Message.user_id == user_id,
                    Message.sent_at < cutoff,
                    Message.deleted_at.is_(None),
                ).values(deleted_at=now)
            )
            log.info("maintenance.data_retention", user_id=str(user_id), retention_days=days)


@celery_app.task(bind=True)
def enforce_data_retention(self):
    """Nightly: soft-delete messages past retention window (per user privacy_settings)."""
    log.info("maintenance.enforce_data_retention.started")
    asyncio.run(_run_enforce_data_retention())

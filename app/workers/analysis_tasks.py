"""
Analysis tasks: message AI analysis (Phase 5), recalculate people importance scores (Phase 4).
EventBus: MessageIngested -> analyze_message.delay(message_id).
"""

import asyncio
from uuid import UUID

import structlog

from app.core.database import get_session_factory
from app.core.events import EventBus, MessageIngested
from app.core.unit_of_work import UnitOfWork
from app.services.people_service import recalculate_importance_score
from app.workers.celery_app import celery_app

log = structlog.get_logger()


async def _run_analyze_message(message_id_str: str) -> None:
    """Load message, run AI pipeline (extract, sentiment, commitments, embedding), update DB."""
    from app.ai.analysis_service import analyze_message as run_analysis

    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        await run_analysis(uow, UUID(message_id_str))


@celery_app.task(bind=True, max_retries=2)
def analyze_message(self, message_id: str):
    """Phase 5: extract entities, sentiment, commitments, embeddings. Idempotent."""
    log.info("analysis.analyze_message.started", message_id=message_id)
    try:
        asyncio.run(_run_analyze_message(message_id))
    except Exception as e:
        log.exception("analysis.analyze_message.failed", message_id=message_id, error=str(e))
        raise self.retry(exc=e)
    log.info("analysis.analyze_message.done", message_id=message_id)


def _on_message_ingested(event: MessageIngested) -> None:
    """Queue AI analysis for the ingested message."""
    analyze_message.delay(str(event.message_id))


# Register so that EventBus.publish(MessageIngested(...)) triggers analyze_message.delay
EventBus.subscribe(MessageIngested, _on_message_ingested)


async def _run_recalculate_people_scores() -> None:
    """Recalculate importance_score for all people."""
    from sqlalchemy import select
    from app.models.person import Person

    factory = get_session_factory()
    count = 0
    async with factory() as session:
        async with session.begin():
            from app.repositories.people_repository import PeopleRepository
            repo = PeopleRepository(session, Person)
            result = await session.execute(select(Person))
            people = list(result.scalars().all())
            for p in people:
                new_score = recalculate_importance_score(p)
                await repo.update(p, importance_score=new_score)
                count += 1
    log.info("analysis.recalculate_scores.done", count=count)


@celery_app.task(bind=True)
def recalculate_all_people_scores(self):
    """Nightly: recalculate importance_score for all people."""
    log.info("analysis.recalculate_all_people_scores.started")
    asyncio.run(_run_recalculate_people_scores())

"""
Insight tasks: pattern insights, briefings, commitment nudges. Phase 7 full implementation.
EventBus: RelationshipSilenceDetected -> generate_insight_task.delay(); CommitmentCreated -> schedule_commitment_nudge_task.delay().
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog

from app.core.database import get_session_factory
from app.core.events import CommitmentCreated, EventBus, RelationshipSilenceDetected
from app.core.unit_of_work import UnitOfWork
from app.workers.celery_app import celery_app

log = structlog.get_logger()

# Minimum silence (days) to emit RelationshipSilenceDetected in nightly run
SILENCE_DAYS_THRESHOLD = 7
# Nudge backoff: first nudge 24h after creation, then +24h per nudge
NUDGE_DELTA_HOURS = 24


async def _run_generate_insight(user_id_str: str, person_id_str: str, days_silent: int) -> None:
    from app.ai.insight_generator import generate_insight_for_silence

    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        await generate_insight_for_silence(
            uow, UUID(user_id_str), UUID(person_id_str), days_silent
        )


@celery_app.task(bind=True, max_retries=2)
def generate_insight_task(self, user_id: str, person_id: str, days_silent: int):
    """Generate a single relationship_silence insight. Triggered by RelationshipSilenceDetected."""
    log.info(
        "insights.generate_insight.started",
        user_id=user_id,
        person_id=person_id,
        days_silent=days_silent,
    )
    try:
        asyncio.run(_run_generate_insight(user_id, person_id, days_silent))
    except Exception as e:
        log.exception(
            "insights.generate_insight.failed",
            user_id=user_id,
            person_id=person_id,
            error=str(e),
        )
        raise self.retry(exc=e)
    log.info("insights.generate_insight.done", user_id=user_id, person_id=person_id)


def _on_relationship_silence_detected(event: RelationshipSilenceDetected) -> None:
    generate_insight_task.delay(
        str(event.user_id), str(event.person_id), event.days_silent
    )


EventBus.subscribe(RelationshipSilenceDetected, _on_relationship_silence_detected)


async def _run_schedule_commitment_nudge(commitment_id_str: str) -> None:
    """Set next_nudge_at on the commitment so the hourly job will create the notification."""
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    first_nudge = now + timedelta(hours=NUDGE_DELTA_HOURS)
    async with UnitOfWork(factory) as uow:
        comm = await uow.commitments.get_by_id(UUID(commitment_id_str))
        if not comm or comm.status != "open":
            return
        await uow.commitments.update(comm, next_nudge_at=first_nudge)
    log.info(
        "insights.schedule_nudge.scheduled",
        commitment_id=commitment_id_str,
        next_nudge_at=first_nudge.isoformat(),
    )


@celery_app.task(bind=True, max_retries=2)
def schedule_commitment_nudge_task(self, commitment_id: str):
    """Schedule first nudge for a new commitment (set next_nudge_at). Triggered by CommitmentCreated."""
    log.info("insights.schedule_commitment_nudge.started", commitment_id=commitment_id)
    try:
        asyncio.run(_run_schedule_commitment_nudge(commitment_id))
    except Exception as e:
        log.exception("insights.schedule_commitment_nudge.failed", commitment_id=commitment_id, error=str(e))
        raise self.retry(exc=e)
    log.info("insights.schedule_commitment_nudge.done", commitment_id=commitment_id)


def _on_commitment_created(event: CommitmentCreated) -> None:
    schedule_commitment_nudge_task.delay(str(event.commitment_id))


EventBus.subscribe(CommitmentCreated, _on_commitment_created)


async def _run_generate_pattern_insights() -> None:
    """Nightly: find users, for each find silent relationships, publish RelationshipSilenceDetected per person."""
    from app.core.events import EventBus as Bus

    factory = get_session_factory()
    published = 0
    async with UnitOfWork(factory) as uow:
        users = await uow.users.list_all_active()
        for user in users:
            silent_pairs = await uow.people.list_silent_since(
                user.id, days=SILENCE_DAYS_THRESHOLD, limit=20
            )
            for person, days_silent in silent_pairs:
                await Bus.publish(
                    RelationshipSilenceDetected(
                        user_id=user.id,
                        person_id=person.id,
                        days_silent=days_silent,
                    )
                )
                published += 1
    log.info("insights.pattern_insights.published", users=len(users), events=published)


@celery_app.task(bind=True)
def generate_pattern_insights(self):
    """Nightly: generate pattern-based insights (publish RelationshipSilenceDetected for silent relationships)."""
    log.info("insights.generate_pattern_insights.started")
    asyncio.run(_run_generate_pattern_insights())
    log.info("insights.generate_pattern_insights.done")


def _user_briefing_time_now(user) -> bool:
    """True if user's local time (by timezone) matches briefing_time (within current minute)."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(user.timezone or "UTC")
        local_now = datetime.now(tz).time()
        brief = user.briefing_time
        return (
            local_now.hour == brief.hour
            and local_now.minute == brief.minute
        )
    except Exception:
        return False


async def _run_send_due_briefings() -> None:
    from app.ai.briefing_generator import generate_daily_briefing

    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        users = await uow.users.list_all_active()
        for user in users:
            if not user.briefing_enabled:
                continue
            if not _user_briefing_time_now(user):
                continue
            try:
                title, body = await generate_daily_briefing(uow, user.id)
            except Exception as e:
                log.warning(
                    "insights.briefing.generate_failed",
                    user_id=str(user.id),
                    error=str(e),
                )
                continue
            insight = await uow.insights.create(
                user_id=user.id,
                insight_type="daily_briefing",
                title=title[:500],
                body=body[:2000],
                summary=title[:500],
                person_ids=None,
                commitment_ids=None,
                message_ids=None,
                importance_score=0.5,
                is_actionable=False,
                status="unread",
            )
            notif_key = f"briefing:{user.id}:{datetime.now(timezone.utc).date().isoformat()}"
            existing = await uow.notifications.get_by_notification_key(notif_key)
            if not existing:
                await uow.notifications.create(
                    user_id=user.id,
                    insight_id=insight.id,
                    commitment_id=None,
                    channel="push",
                    title=title[:200],
                    body=body[:500],
                    action_url=None,
                    status="pending",
                    notification_key=notif_key,
                )
            log.info("insights.briefing.scheduled", user_id=str(user.id))


@celery_app.task(bind=True)
def send_due_briefings(self):
    """Every minute: send morning briefings to users whose briefing_time is now."""
    log.info("insights.send_due_briefings.started")
    asyncio.run(_run_send_due_briefings())
    log.info("insights.send_due_briefings.done")


async def _run_schedule_commitment_nudges() -> None:
    """Hourly: create pending notifications for commitments due for nudge; update next_nudge_at."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    next_nudge = now + timedelta(hours=NUDGE_DELTA_HOURS)
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        due = await uow.commitments.list_due_for_nudge(limit=50)
        for comm in due:
            nudge_key = f"nudge:{comm.id}:{comm.nudge_count or 0}"
            existing = await uow.notifications.get_by_notification_key(nudge_key)
            if existing:
                continue
            desc = (comm.description or "")[:150]
            title = "Commitment reminder"
            body = desc or "You have an open commitment to follow up on."
            await uow.notifications.create(
                user_id=comm.user_id,
                insight_id=None,
                commitment_id=comm.id,
                channel="push",
                title=title,
                body=body,
                action_url=None,
                status="pending",
                notification_key=nudge_key,
            )
            nudge_count = (comm.nudge_count or 0) + 1
            await uow.commitments.update(
                comm,
                last_nudged_at=now,
                nudge_count=nudge_count,
                next_nudge_at=next_nudge,
            )
        log.info("insights.schedule_nudges.created", count=len(due))


@celery_app.task(bind=True)
def schedule_commitment_nudges(self):
    """Hourly: schedule nudges for open commitments (create pending notifications, update next_nudge_at)."""
    log.info("insights.schedule_commitment_nudges.started")
    asyncio.run(_run_schedule_commitment_nudges())
    log.info("insights.schedule_commitment_nudges.done")

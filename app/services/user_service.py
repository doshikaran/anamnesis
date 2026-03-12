"""
User service: account deletion (GDPR). Revoke OAuth, Stripe, S3 cleanup, bulk DB delete, Redis purge.
"""

import hashlib
from datetime import datetime, timezone
import structlog
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.database import get_session_factory
from app.core.encryption import decrypt_token
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.models.usage_event import UsageEvent
from app.models.notification import Notification
from app.models.query import Query
from app.models.insight import Insight
from app.models.relationship_event import RelationshipEvent
from app.models.commitment import Commitment
from app.models.message import Message
from app.models.thread import Thread
from app.models.person import Person
from app.models.ingestion_job import IngestionJob
from app.models.privacy_settings import PrivacySettings
from app.models.connection import Connection

log = structlog.get_logger()

# Bulk delete order (respects FK constraints)
TABLES_IN_ORDER = [
    UsageEvent,
    Notification,
    Query,
    Insight,
    RelationshipEvent,
    Commitment,
    Message,
    Thread,
    Person,
    IngestionJob,
    PrivacySettings,
    Connection,
    User,
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def delete_user_account(
    session_factory: async_sessionmaker[AsyncSession],
    user: User,
    redis: Redis,
) -> None:
    """
    Permanently delete user account (GDPR). Order: set flag, revoke OAuth, Stripe, queue S3,
    bulk delete DB, purge Redis, log. Never block on OAuth/Stripe failure.
    """
    user_id = user.id
    email = user.email or ""

    # 1. Set delete_requested_at, flush, log
    async with UnitOfWork(session_factory) as uow:
        await uow.users.update(user, delete_requested_at=_utcnow())
        await uow.session.flush()
    log.info("account.deletion.started", user_id=str(user_id))

    # 2. Revoke OAuth tokens — best effort
    async with UnitOfWork(session_factory) as uow:
        connections = await uow.connections.list_by_user(user_id)
    import httpx
    for conn in connections:
        try:
            token = decrypt_token(user_id, conn.access_token or "")
            if not token:
                continue
            if conn.source_type in ("gmail", "google_calendar"):
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": token},
                    )
                log.info(
                    "account.deletion.revoke",
                    user_id=str(user_id),
                    source_type=conn.source_type,
                    status_code=getattr(r, "status_code", None),
                )
            elif conn.source_type in ("outlook_mail", "outlook_calendar", "teams"):
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        "https://login.microsoftonline.com/common/oauth2/v2.0/logout",
                        params={"token": token},
                    )
                log.info(
                    "account.deletion.revoke",
                    user_id=str(user_id),
                    source_type=conn.source_type,
                    status_code=getattr(r, "status_code", None),
                )
        except Exception as e:
            log.warning(
                "account.deletion.revoke_failed",
                user_id=str(user_id),
                source_type=conn.source_type,
                error=str(e),
            )

    # 3. Stripe cancellation — best effort
    if getattr(user, "stripe_sub_id", None):
        try:
            import stripe
            stripe.Subscription.cancel(user.stripe_sub_id)
            log.info("account.deletion.stripe_cancelled", user_id=str(user_id))
        except Exception as e:
            log.warning("account.deletion.stripe_failed", user_id=str(user_id), error=str(e))

    # 4. Queue S3 cleanup via Celery
    try:
        from app.workers.maintenance_tasks import cleanup_user_s3
        cleanup_user_s3.delay(str(user_id))
        log.info("account.deletion.s3_queued", user_id=str(user_id))
    except Exception as e:
        log.warning("account.deletion.s3_queue_failed", user_id=str(user_id), error=str(e))

    # 5. Bulk delete in order
    async with UnitOfWork(session_factory) as uow:
        for model in TABLES_IN_ORDER:
            field = User.id if model == User else model.user_id
            await uow.session.execute(delete(model).where(field == user_id))

    # 6. Purge Redis
    await redis.delete(f"refresh:{user_id}")
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"rate_limit:{user_id}:*", count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break
    await redis.delete(f"user_context:{user_id}")

    # 7. Log completion with email hash only
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    log.info("account.deletion.complete", user_id=str(user_id), email_hash=email_hash)

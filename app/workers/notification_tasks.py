"""
Notification tasks: send pending push notifications. Phase 7 full implementation.
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import structlog

from app.core.database import get_session_factory
from app.core.push import send_push
from app.core.unit_of_work import UnitOfWork
from app.workers.celery_app import celery_app

log = structlog.get_logger()


async def _run_send_pending_notifications() -> None:
    """Poll notifications table for status=pending; send via push; update status/sent_at/failed_reason."""
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        pending = await uow.notifications.list_pending(limit=50)
        for n in pending:
            if n.channel != "push":
                await uow.notifications.update(n, status="failed", failed_reason="Unsupported channel")
                continue
            user = await uow.users.get_by_id(n.user_id)
            if not user:
                await uow.notifications.update(n, status="failed", failed_reason="User not found")
                continue
            if not user.push_enabled or not user.push_endpoint or not user.push_p256dh or not user.push_auth:
                await uow.notifications.update(n, status="failed", failed_reason="User has no push subscription")
                continue
            success, err = send_push(
                endpoint=user.push_endpoint,
                p256dh=user.push_p256dh,
                auth=user.push_auth,
                title=n.title,
                body=n.body,
                action_url=n.action_url,
            )
            now = datetime.now(timezone.utc)
            if success:
                await uow.notifications.update(
                    n,
                    status="sent",
                    sent_at=now,
                    delivered_at=now,
                )
                log.info("notifications.sent", notification_id=str(n.id), user_id=str(n.user_id))
            else:
                await uow.notifications.update(
                    n,
                    status="failed",
                    sent_at=now,
                    failed_reason=(err or "Unknown error")[:500],
                )
                log.warning(
                    "notifications.failed",
                    notification_id=str(n.id),
                    user_id=str(n.user_id),
                    reason=err,
                )


@celery_app.task(bind=True)
def send_pending_notifications(self):
    """Every minute: poll notifications table and send pending push."""
    log.info("notifications.send_pending.started")
    asyncio.run(_run_send_pending_notifications())
    log.info("notifications.send_pending.done")

"""
Notifications API: list, get. Push subscription is under /users/me/push-subscription.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository

router = APIRouter()
log = structlog.get_logger()


def _notification_to_item(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "insight_id": str(n.insight_id) if n.insight_id else None,
        "commitment_id": str(n.commitment_id) if n.commitment_id else None,
        "channel": n.channel,
        "title": n.title,
        "body": n.body,
        "action_url": n.action_url,
        "status": n.status,
        "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        "delivered_at": n.delivered_at.isoformat() if n.delivered_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List notifications for the current user."""
    repo = NotificationRepository(db, Notification)
    items = await repo.list_by_user(
        current_user.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": [_notification_to_item(n) for n in items]}


@router.get("/{id}")
async def get_notification(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single notification by id."""
    repo = NotificationRepository(db, Notification)
    notif = await repo.get_by_id_and_user(id, current_user.id)
    if not notif:
        raise NotFoundError(code="NOTIFICATION_NOT_FOUND", message="Notification not found")
    return _notification_to_item(notif)

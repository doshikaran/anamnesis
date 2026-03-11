"""Notification repository. All notification data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession, model: type[Notification] = Notification):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(Notification.id == id, Notification.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_notification_key(self, notification_key: str) -> Notification | None:
        result = await self.session.execute(select(Notification).where(Notification.notification_key == notification_key))
        return result.scalar_one_or_none()

    async def create_if_not_exists(self, notification_key: str, **kwargs: object) -> Notification | None:
        existing = await self.get_by_notification_key(notification_key)
        if existing:
            return None
        return await self.create(notification_key=notification_key, **kwargs)

    async def list_pending(self, limit: int = 100) -> list[Notification]:
        """Notifications with status pending, ordered by created_at (for send_pending_notifications)."""
        q = (
            select(Notification)
            .where(Notification.status == "pending")
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        q = select(Notification).where(Notification.user_id == user_id)
        if status is not None:
            q = q.where(Notification.status == status)
        q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

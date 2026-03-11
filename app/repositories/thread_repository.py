"""Thread repository. All thread data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import Thread
from app.repositories.base import BaseRepository


class ThreadRepository(BaseRepository[Thread]):
    def __init__(self, session: AsyncSession, model: type[Thread] = Thread):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Thread | None:
        result = await self.session.execute(select(Thread).where(Thread.id == id, Thread.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_external(self, user_id: UUID, source_type: str, external_thread_id: str) -> Thread | None:
        result = await self.session.execute(
            select(Thread).where(
                Thread.user_id == user_id,
                Thread.source_type == source_type,
                Thread.external_thread_id == external_thread_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        source_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Thread]:
        q = select(Thread).where(Thread.user_id == user_id)
        if source_type is not None:
            q = q.where(Thread.source_type == source_type)
        q = q.order_by(Thread.last_message_at.desc().nullslast()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

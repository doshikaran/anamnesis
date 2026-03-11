"""Insight repository. All insight data access."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insight import Insight
from app.repositories.base import BaseRepository


class InsightRepository(BaseRepository[Insight]):
    def __init__(self, session: AsyncSession, model: type[Insight] = Insight):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Insight | None:
        result = await self.session.execute(select(Insight).where(Insight.id == id, Insight.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        insight_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[Insight], str | None]:
        q = select(Insight).where(Insight.user_id == user_id)
        if insight_type is not None:
            q = q.where(Insight.insight_type == insight_type)
        if status is not None:
            q = q.where(Insight.status == status)
        if cursor:
            try:
                ts = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
                q = q.where(Insight.created_at < ts)
            except Exception:
                pass
        q = q.order_by(Insight.created_at.desc()).limit(limit + 1)
        result = await self.session.execute(q)
        rows = list(result.scalars().all())
        next_cursor = rows[limit].created_at.isoformat() if len(rows) > limit else None
        return rows[:limit], next_cursor

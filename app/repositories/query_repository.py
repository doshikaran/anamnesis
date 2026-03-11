"""Query repository. NL query history data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query import Query
from app.repositories.base import BaseRepository


class QueryRepository(BaseRepository[Query]):
    def __init__(self, session: AsyncSession, model: type[Query] = Query):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Query | None:
        result = await self.session.execute(select(Query).where(Query.id == id, Query.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID, limit: int = 50, offset: int = 0):
        result = await self.session.execute(
            select(Query).where(Query.user_id == user_id).order_by(Query.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

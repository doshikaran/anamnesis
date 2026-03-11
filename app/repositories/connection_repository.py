"""Connection repository. All connection data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.repositories.base import BaseRepository


class ConnectionRepository(BaseRepository[Connection]):
    def __init__(self, session: AsyncSession, model: type[Connection] = Connection):
        super().__init__(session, model)

    async def list_by_user(self, user_id: UUID) -> list[Connection]:
        result = await self.session.execute(
            select(Connection).where(Connection.user_id == user_id).order_by(Connection.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Connection | None:
        result = await self.session.execute(
            select(Connection).where(Connection.id == id, Connection.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_source_type(self, user_id: UUID, source_type: str) -> Connection | None:
        result = await self.session.execute(
            select(Connection).where(Connection.user_id == user_id, Connection.source_type == source_type)
        )
        return result.scalar_one_or_none()

    async def list_active_for_sync(self) -> list[Connection]:
        """All connections that are active and sync_enabled (for Celery beat sync_all)."""
        result = await self.session.execute(
            select(Connection).where(
                Connection.status == "active",
                Connection.sync_enabled.is_(True),
            )
        )
        return list(result.scalars().all())

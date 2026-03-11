"""User repository. All user data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession, model: type[User] = User):
        super().__init__(session, model)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def get_by_google_id(self, google_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.google_id == google_id, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def get_by_microsoft_id(self, microsoft_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.microsoft_id == microsoft_id, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def get_by_id_active(self, id: UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == id, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def list_all_active(self, limit: int = 5000) -> list[User]:
        """List all non-deleted users. Used by beat jobs (briefings, nightly insights)."""
        result = await self.session.execute(
            select(User).where(User.deleted_at.is_(None)).limit(limit)
        )
        return list(result.scalars().all())

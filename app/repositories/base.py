"""
Generic BaseRepository[T]. All DB access goes through repositories.
No business logic — data access only. All methods async.
"""

from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic repository with get_by_id, list, create, update, soft_delete where applicable."""

    def __init__(self, session: AsyncSession, model: type[ModelT]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: UUID) -> ModelT | None:
        result = await self.session.get(self.model, id)
        return result

    async def create(self, **kwargs: object) -> ModelT:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: ModelT, **kwargs: object) -> ModelT:
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def soft_delete(self, instance: ModelT, deleted_at_column: str = "deleted_at") -> None:
        if hasattr(instance, deleted_at_column):
            setattr(instance, deleted_at_column, datetime.now(timezone.utc))
            await self.session.flush()

"""Message repository. All message data access."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    def __init__(self, session: AsyncSession, model: type[Message] = Message):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Message | None:
        result = await self.session.execute(
            select(Message).where(Message.id == id, Message.user_id == user_id, Message.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(self, user_id: UUID, source_type: str, external_id: str) -> Message | None:
        result = await self.session.execute(
            select(Message).where(
                Message.user_id == user_id,
                Message.source_type == source_type,
                Message.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, user_id: UUID, content_hash: str) -> Message | None:
        result = await self.session.execute(
            select(Message).where(Message.user_id == user_id, Message.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def get_for_person(
        self,
        user_id: UUID,
        person_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Messages where person is sender or in recipients. Chronological."""
        q = (
            select(Message)
            .where(Message.user_id == user_id, Message.deleted_at.is_(None))
            .where(
                (Message.sender_person_id == person_id) | (Message.recipient_person_ids.contains([person_id]))
            )
            .order_by(Message.sent_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_search(
        self,
        user_id: UUID,
        *,
        person_id: UUID | None = None,
        source_type: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Message]:
        """Search messages by filters. Optional full-text q can be added later."""
        q = select(Message).where(Message.user_id == user_id, Message.deleted_at.is_(None))
        if person_id is not None:
            q = q.where(
                (Message.sender_person_id == person_id) | (Message.recipient_person_ids.contains([person_id]))
            )
        if source_type is not None:
            q = q.where(Message.source_type == source_type)
        if from_date is not None:
            q = q.where(Message.sent_at >= from_date)
        if to_date is not None:
            q = q.where(Message.sent_at <= to_date)
        q = q.order_by(Message.sent_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def semantic_search(
        self,
        user_id: UUID,
        embedding: list[float],
        *,
        limit: int = 20,
        threshold: float | None = None,
    ) -> list[Message]:
        """Vector similarity search on message embedding (cosine). HNSW index."""
        q = (
            select(Message)
            .where(Message.user_id == user_id, Message.deleted_at.is_(None), Message.embedding.isnot(None))
            .order_by(Message.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def hybrid_search(
        self,
        user_id: UUID,
        embedding: list[float],
        *,
        person_id: UUID | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        has_commitment: bool | None = None,
        limit: int = 20,
    ) -> list[Message]:
        """Hybrid: pgvector cosine similarity on message embeddings + structured filters.
        Combines vector search with person, date range, and commitment filters.
        """
        q = (
            select(Message)
            .where(Message.user_id == user_id, Message.deleted_at.is_(None), Message.embedding.isnot(None))
        )
        if person_id is not None:
            q = q.where(
                (Message.sender_person_id == person_id) | (Message.recipient_person_ids.contains([person_id]))
            )
        if from_date is not None:
            q = q.where(Message.sent_at >= from_date)
        if to_date is not None:
            q = q.where(Message.sent_at <= to_date)
        if has_commitment is not None:
            q = q.where(Message.has_commitment == has_commitment)
        q = q.order_by(Message.embedding.cosine_distance(embedding)).limit(limit)
        result = await self.session.execute(q)
        return list(result.scalars().all())

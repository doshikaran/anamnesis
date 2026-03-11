"""Relationship event repository. All relationship_events data access."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.relationship_event import RelationshipEvent
from app.repositories.base import BaseRepository


class RelationshipEventRepository(BaseRepository[RelationshipEvent]):
    def __init__(self, session: AsyncSession, model: type[RelationshipEvent] = RelationshipEvent):
        super().__init__(session, model)

    async def list_by_person(self, user_id: UUID, person_id: UUID, limit: int = 50) -> list[RelationshipEvent]:
        result = await self.session.execute(
            select(RelationshipEvent)
            .where(
                RelationshipEvent.user_id == user_id,
                RelationshipEvent.person_id == person_id,
            )
            .order_by(RelationshipEvent.event_date.desc().nullslast(), RelationshipEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

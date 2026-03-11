"""Commitment repository. All commitment data access."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment
from app.repositories.base import BaseRepository


class CommitmentRepository(BaseRepository[Commitment]):
    def __init__(self, session: AsyncSession, model: type[Commitment] = Commitment):
        super().__init__(session, model)

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Commitment | None:
        result = await self.session.execute(
            select(Commitment).where(Commitment.id == id, Commitment.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        status: str | None = None,
        person_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        q = select(Commitment).where(Commitment.user_id == user_id)
        if status is not None:
            q = q.where(Commitment.status == status)
        if person_id is not None:
            q = q.where(Commitment.person_id == person_id)
        q = q.order_by(Commitment.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def list_due_for_nudge(self, limit: int = 100) -> list[Commitment]:
        """Open commitments where next_nudge_at <= now or (next_nudge_at is null and created 24h+ ago)."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)
        q = (
            select(Commitment)
            .where(Commitment.status == "open")
            .where(
                or_(
                    and_(Commitment.next_nudge_at.is_(None), Commitment.created_at <= day_ago),
                    and_(Commitment.next_nudge_at.isnot(None), Commitment.next_nudge_at <= now),
                )
            )
            .order_by(Commitment.next_nudge_at.asc().nullsfirst())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

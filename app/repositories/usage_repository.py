"""Usage event repository. AI/usage tracking."""

from datetime import date
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage_event import UsageEvent
from app.repositories.base import BaseRepository


class UsageRepository(BaseRepository[UsageEvent]):
    def __init__(self, session: AsyncSession, model: type[UsageEvent] = UsageEvent):
        super().__init__(session, model)

    async def log_ai_call(
        self,
        user_id: UUID,
        event_type: str,
        *,
        model_used: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        tokens_cached: int | None = None,
        cost_usd: float | None = None,
        reference_id: UUID | None = None,
        reference_type: str | None = None,
    ) -> UsageEvent:
        return await self.create(
            user_id=user_id,
            event_type=event_type,
            model_used=model_used,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_cached=tokens_cached,
            cost_usd=cost_usd or 0.0,
            reference_id=reference_id,
            reference_type=reference_type,
        )

    async def get_daily_usage(self, user_id: UUID, d: date | None = None) -> int:
        from datetime import datetime, timezone
        day = d or date.today()
        start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = datetime.combine(day, datetime.max.time()).replace(tzinfo=timezone.utc)
        result = await self.session.execute(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= start,
                UsageEvent.created_at <= end,
            )
        )
        return int(result.scalar() or 0)

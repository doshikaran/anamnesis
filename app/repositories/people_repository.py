"""People repository. All person data access."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person
from app.repositories.base import BaseRepository


class PeopleRepository(BaseRepository[Person]):
    def __init__(self, session: AsyncSession, model: type[Person] = Person):
        super().__init__(session, model)

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        relationship_type: str | None = None,
        is_starred: bool | None = None,
        importance_gte: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Person]:
        q = select(Person).where(Person.user_id == user_id)
        if relationship_type is not None:
            q = q.where(Person.relationship_type == relationship_type)
        if is_starred is not None:
            q = q.where(Person.is_starred == is_starred)
        if importance_gte is not None:
            q = q.where(Person.importance_score >= importance_gte)
        q = q.order_by(Person.last_contact_at.desc().nullslast()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_by_id_and_user(self, id: UUID, user_id: UUID) -> Person | None:
        result = await self.session.execute(select(Person).where(Person.id == id, Person.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_silent_since(self, user_id: UUID, days: int, limit: int = 50) -> list[tuple[Person, int]]:
        """People with last_contact_at at least `days` ago (or never). Returns list of (Person, days_silent)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (
            select(Person)
            .where(Person.user_id == user_id)
            .where(Person.last_contact_at.is_(None) | (Person.last_contact_at <= since))
            .order_by(Person.last_contact_at.asc().nullsfirst())
            .limit(limit)
        )
        result = await self.session.execute(q)
        people = list(result.scalars().all())
        out: list[tuple[Person, int]] = []
        for p in people:
            if p.last_contact_at:
                delta = datetime.now(timezone.utc) - p.last_contact_at.replace(tzinfo=timezone.utc)
                days_silent = max(days, int(delta.total_seconds() / 86400))
            else:
                days_silent = days
            out.append((p, days_silent))
        return out

    async def get_by_canonical_email(self, user_id: UUID, email: str) -> Person | None:
        result = await self.session.execute(
            select(Person).where(Person.user_id == user_id, Person.canonical_email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, user_id: UUID, email: str) -> Person | None:
        """Match canonical_email or any value in all_emails array."""
        normalized = email.strip().lower() if email else ""
        if not normalized:
            return None
        # Try canonical first
        person = await self.get_by_canonical_email(user_id, normalized)
        if person:
            return person
        # Match in all_emails (value = ANY(array))
        result = await self.session.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.all_emails.any(normalized),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(self, user_id: UUID, source: str, external_id: str) -> Person | None:
        """Find person by external_ids JSONB key (e.g. source='gmail', external_id='user-id')."""
        if not source or not external_id:
            return None
        result = await self.session.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.external_ids.has_key(source),
                Person.external_ids[source].astext == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def search_by_name_trigram(self, user_id: UUID, query: str, limit: int = 20) -> list[Person]:
        """Search by display_name (ilike for broad match; pg_trgm similarity when available)."""
        if not query or not query.strip():
            return []
        pattern = f"%{query.strip()}%"
        q = (
            select(Person)
            .where(Person.user_id == user_id)
            .where(Person.display_name.ilike(pattern))
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def find_merge_candidates(self, user_id: UUID, similarity_threshold: float = 0.5) -> list[tuple[Person, Person, float]]:
        """Find pairs of people that may be duplicates (high name similarity). Uses pg_trgm similarity."""
        stmt = text("""
            SELECT a.id AS a_id, b.id AS b_id,
                   similarity(a.display_name, b.display_name) AS sim
            FROM people a
            JOIN people b ON a.user_id = b.user_id AND a.id < b.id
            WHERE a.user_id = :user_id
              AND (a.merged_from IS NULL OR a.is_merged = FALSE)
              AND (b.merged_from IS NULL OR b.is_merged = FALSE)
              AND similarity(a.display_name, b.display_name) > :threshold
        """)
        result = await self.session.execute(stmt, {"user_id": str(user_id), "threshold": similarity_threshold})
        rows = result.fetchall()
        out: list[tuple[Person, Person, float]] = []
        for row in rows:
            a = await self.get_by_id(UUID(row.a_id))
            b = await self.get_by_id(UUID(row.b_id))
            if a and b:
                out.append((a, b, float(row.sim)))
        return out

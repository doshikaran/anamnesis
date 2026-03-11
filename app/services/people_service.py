"""
People service: person resolution, merging, contact stats, importance scoring.
Uses repositories only. No raw SQL.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.models.person import Person
from app.repositories.people_repository import PeopleRepository
from app.utils.email_utils import normalize_email, extract_name_from_email

if TYPE_CHECKING:
    from app.core.unit_of_work import UnitOfWork


async def resolve_or_create_person(
    repo: PeopleRepository,
    user_id: UUID,
    *,
    email: str | None = None,
    display_name: str | None = None,
    source: str = "manual",
    external_id: str | None = None,
) -> Person:
    """
    Resolve to an existing person or create new. Match order: external_id, email, then name trigram.
    Returns Person ORM. Used by message ingestion and manual input.
    """
    # 1. Match by external_id
    if source and external_id:
        existing = await repo.get_by_external_id(user_id, source, external_id)
        if existing:
            return existing

    # 2. Match by email
    normalized_email = normalize_email(email) if email else None
    if normalized_email:
        existing = await repo.get_by_email(user_id, normalized_email)
        if existing:
            if external_id and source and existing.external_ids:
                ext = dict(existing.external_ids or {})
                ext[source] = external_id
                await repo.update(existing, external_ids=ext)
            elif external_id and source:
                await repo.update(existing, external_ids={source: external_id})
            return existing

    # 3. No match: create new person
    name = (display_name or "").strip() or (extract_name_from_email(normalized_email or "") if normalized_email else "Unknown")
    all_emails = [normalized_email] if normalized_email else []
    external_ids = {source: external_id} if (source and external_id) else {}
    sources_list = [source] if source else []
    return await repo.create(
        user_id=user_id,
        display_name=name,
        canonical_email=normalized_email,
        all_emails=all_emails,
        external_ids=external_ids,
        sources=sources_list,
        relationship_type="contact",
    )


async def merge_people(
    uow: "UnitOfWork",
    user_id: UUID,
    primary_id: UUID,
    secondary_id: UUID,
) -> Person:
    """
    Merge secondary into primary. Updates all FK references (messages, commitments, events)
    to primary, then merges person fields and marks secondary merged.
    """
    repo = uow.people
    primary = await repo.get_by_id_and_user(primary_id, user_id)
    secondary = await repo.get_by_id_and_user(secondary_id, user_id)
    if not primary:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Primary person not found")
    if not secondary:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Secondary person not found")
    if primary.id == secondary.id:
        raise ValidationError(code="SAME_PERSON", message="Cannot merge same person")

    # Update FKs: messages (sender_person_id, recipient_person_ids), commitments (person_id), events (person_id)
    from sqlalchemy import update
    from app.models.message import Message
    from app.models.commitment import Commitment
    from app.models.relationship_event import RelationshipEvent

    await uow.session.execute(
        update(Message).where(Message.user_id == user_id, Message.sender_person_id == secondary_id).values(sender_person_id=primary_id)
    )
    # recipient_person_ids: replace secondary_id with primary_id in array (PostgreSQL: array_replace or do in Python per row)
    msgs_with_recip = await uow.messages.get_for_person(user_id, secondary_id, limit=10000, offset=0)
    for msg in msgs_with_recip:
        if msg.recipient_person_ids:
            new_ids = [primary_id if p == secondary_id else p for p in msg.recipient_person_ids]
            await uow.session.execute(update(Message).where(Message.id == msg.id).values(recipient_person_ids=new_ids))
    await uow.session.execute(
        update(Commitment).where(Commitment.user_id == user_id, Commitment.person_id == secondary_id).values(person_id=primary_id)
    )
    await uow.session.execute(
        update(RelationshipEvent).where(RelationshipEvent.user_id == user_id, RelationshipEvent.person_id == secondary_id).values(person_id=primary_id)
    )

    all_emails = list(set((primary.all_emails or []) + (secondary.all_emails or [])))
    phone_numbers = list(set((primary.phone_numbers or []) + (secondary.phone_numbers or [])))
    sources = list(set((primary.sources or []) + (secondary.sources or [])))
    external_ids = {**(primary.external_ids or {}), **(secondary.external_ids or {})}
    merged_from = list((primary.merged_from or []) + [secondary.id])

    await repo.update(
        primary,
        all_emails=all_emails,
        phone_numbers=phone_numbers,
        sources=sources,
        external_ids=external_ids,
        merged_from=merged_from,
        is_merged=True,
    )
    await repo.update(secondary, is_merged=True)
    return primary


async def update_contact_stats(
    repo: PeopleRepository,
    person_id: UUID,
    user_id: UUID,
    *,
    last_contact_at: datetime | None = None,
    last_outbound_at: datetime | None = None,
    last_inbound_at: datetime | None = None,
) -> None:
    """Update last_contact_at and direction-specific timestamps for a person."""
    person = await repo.get_by_id_and_user(person_id, user_id)
    if not person:
        return
    updates = {}
    if last_contact_at is not None:
        updates["last_contact_at"] = last_contact_at
    if last_outbound_at is not None:
        updates["last_outbound_at"] = last_outbound_at
    if last_inbound_at is not None:
        updates["last_inbound_at"] = last_inbound_at
    if updates:
        await repo.update(person, **updates)


def recalculate_importance_score(person: Person) -> float:
    """
    Simple importance heuristic from contact recency and frequency. Returns 0..1.
    Can be replaced with ML later.
    """
    score = 0.5
    if person.last_contact_at:
        days_ago = (datetime.now(timezone.utc) - person.last_contact_at.replace(tzinfo=timezone.utc)).days
        if days_ago <= 7:
            score += 0.2
        elif days_ago <= 30:
            score += 0.1
    if person.is_starred:
        score += 0.15
    return min(1.0, score)


async def find_and_queue_merge_candidates(
    repo: PeopleRepository,
    user_id: UUID,
    similarity_threshold: float = 0.5,
) -> list[tuple[Person, Person, float]]:
    """Find person pairs that may be duplicates (for nightly job or admin review)."""
    return await repo.find_merge_candidates(user_id, similarity_threshold=similarity_threshold)

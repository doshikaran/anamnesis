"""
People API: list, get, update, delete, timeline, commitments, events, merge, search.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import NotFoundError
from app.core.rate_limiter import rate_limit
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.person import Person
from app.repositories.people_repository import PeopleRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.commitment_repository import CommitmentRepository
from app.repositories.relationship_event_repository import RelationshipEventRepository
from app.models.message import Message
from app.models.commitment import Commitment
from app.models.relationship_event import RelationshipEvent
from app.schemas.person import (
    PersonResponse,
    PersonDetailResponse,
    PersonUpdateSchema,
    RelationshipTimelineItem,
    MergeRequestSchema,
    person_to_response,
    person_to_detail_response,
)
from app.schemas.message import message_to_response
from app.services.people_service import merge_people

router = APIRouter()
log = structlog.get_logger()


def get_people_repository(db: AsyncSession = Depends(get_db)) -> PeopleRepository:
    return PeopleRepository(db, Person)


@router.get("", response_model=list[PersonResponse])
async def list_people(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    relationship_type: str | None = Query(None),
    importance_gte: float | None = Query(None),
    is_starred: bool | None = Query(None),
    sort: str = Query("last_contact"),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all people with optional filters."""
    repo = PeopleRepository(db, Person)
    people = await repo.list_by_user(
        current_user.id,
        relationship_type=relationship_type,
        is_starred=is_starred,
        importance_gte=importance_gte,
        limit=limit,
        offset=offset,
    )
    return [person_to_response(p) for p in people]


@router.get("/search", response_model=list[PersonResponse])
async def search_people(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=50),
):
    """Search people by name or email."""
    repo = PeopleRepository(db, Person)
    people = await repo.search_by_name_trigram(current_user.id, q, limit=limit)
    return [person_to_response(p) for p in people]


@router.get("/{id}", response_model=PersonDetailResponse)
async def get_person(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full person profile."""
    repo = PeopleRepository(db, Person)
    person = await repo.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    return person_to_detail_response(person)


@router.patch("/{id}", response_model=PersonResponse, dependencies=[rate_limit(30, 60, "people_patch")])
async def update_person(
    id: UUID,
    body: PersonUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update relationship_type, label, starred, display_name."""
    repo = PeopleRepository(db, Person)
    person = await repo.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await repo.update(person, **updates)
        await db.flush()
    return person_to_response(person)


@router.delete("/{id}", status_code=204)
async def delete_person(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete person (and unlink from messages/commitments)."""
    repo = PeopleRepository(db, Person)
    person = await repo.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    await db.delete(person)
    await db.flush()


@router.get("/{id}/timeline", response_model=list[RelationshipTimelineItem])
async def get_person_timeline(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """All messages with this person (chronological)."""
    repo_people = PeopleRepository(db, Person)
    person = await repo_people.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    repo_msg = MessageRepository(db, Message)
    messages = await repo_msg.get_for_person(current_user.id, person.id, limit=limit, offset=offset)
    items = [
        RelationshipTimelineItem(
            id=str(m.id),
            type="message",
            subject=m.subject,
            body_preview=(m.body_clean[:200] + "..." if m.body_clean and len(m.body_clean) > 200 else m.body_clean),
            sent_at=m.sent_at,
        )
        for m in messages
    ]
    return items


@router.get("/{id}/commitments")
async def get_person_commitments(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All commitments involving this person."""
    repo_people = PeopleRepository(db, Person)
    person = await repo_people.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    repo_comm = CommitmentRepository(db, Commitment)
    commitments = await repo_comm.list_by_user(current_user.id, person_id=person.id)
    return [{"id": str(c.id), "description": c.description, "status": c.status, "deadline_at": c.deadline_at} for c in commitments]


@router.get("/{id}/events")
async def get_person_events(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    """All relationship events for this person."""
    repo_people = PeopleRepository(db, Person)
    person = await repo_people.get_by_id_and_user(id, current_user.id)
    if not person:
        raise NotFoundError(code="PERSON_NOT_FOUND", message="Person not found")
    repo_events = RelationshipEventRepository(db, RelationshipEvent)
    events = await repo_events.list_by_person(current_user.id, person.id, limit=limit)
    return [
        RelationshipTimelineItem(
            id=str(e.id),
            type="event",
            event_type=e.event_type,
            description=e.description,
            event_date=e.event_date.isoformat() if e.event_date else None,
        )
        for e in events
    ]


@router.post("/merge")
async def merge_people_endpoint(
    body: MergeRequestSchema,
    current_user: User = Depends(get_current_user),
):
    """Merge two person records. Primary is kept; secondary is merged in."""
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        primary = await merge_people(uow, current_user.id, body.primary_id, body.secondary_id)
    log.info("people.merged", user_id=str(current_user.id), primary_id=str(primary.id), secondary_id=str(body.secondary_id))
    return {"merged": True, "primary_id": str(primary.id)}

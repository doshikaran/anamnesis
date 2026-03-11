"""
Messages API: search, single message, manual note, thread list, single thread.
"""

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import NotFoundError
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.message import Message
from app.models.thread import Thread
from app.repositories.message_repository import MessageRepository
from app.repositories.thread_repository import ThreadRepository
from app.schemas.message import (
    MessageResponse,
    MessageSearchParams,
    ThreadResponse,
    ThreadDetailResponse,
    ManualNoteCreateSchema,
    message_to_response,
    thread_to_response,
)
from app.services.message_service import ingest_message
from app.utils.datetime_utils import utcnow

router = APIRouter()
log = structlog.get_logger()


@router.get("", response_model=list[MessageResponse])
async def search_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None),
    person_id: UUID | None = Query(None),
    source_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Search messages by person, source, date range. Optional q for future full-text."""
    repo = MessageRepository(db, Message)
    messages = await repo.list_search(
        current_user.id,
        person_id=person_id,
        source_type=source_type,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return [message_to_response(m) for m in messages]


@router.get("/threads", response_model=list[ThreadResponse])
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    source_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List threads for the user."""
    repo = ThreadRepository(db, Thread)
    threads = await repo.list_by_user(current_user.id, source_type=source_type, limit=limit, offset=offset)
    return [thread_to_response(t) for t in threads]


@router.get("/threads/{id}", response_model=ThreadDetailResponse)
async def get_thread(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Single thread with messages."""
    repo_thread = ThreadRepository(db, Thread)
    thread = await repo_thread.get_by_id_and_user(id, current_user.id)
    if not thread:
        raise NotFoundError(code="THREAD_NOT_FOUND", message="Thread not found")
    repo_msg = MessageRepository(db, Message)
    # Get messages for this thread (by db_thread_id)
    from sqlalchemy import select
    result = await db.execute(
        select(Message)
        .where(Message.user_id == current_user.id, Message.db_thread_id == thread.id, Message.deleted_at.is_(None))
        .order_by(Message.sent_at.asc())
    )
    messages = list(result.scalars().all())
    detail = thread_to_response(thread)
    return ThreadDetailResponse(**detail.model_dump(), messages=[message_to_response(m) for m in messages])


@router.get("/{id}", response_model=MessageResponse)
async def get_message(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Single message by id."""
    repo = MessageRepository(db, Message)
    msg = await repo.get_by_id_and_user(id, current_user.id)
    if not msg:
        raise NotFoundError(code="MESSAGE_NOT_FOUND", message="Message not found")
    return message_to_response(msg)


@router.post("/manual", response_model=MessageResponse)
async def create_manual_note(
    body: ManualNoteCreateSchema,
    current_user: User = Depends(get_current_user),
):
    """Create manual note or attach voice note (audio_s3_key + transcript)."""
    factory = get_session_factory()
    body_text = (body.body_text or "").strip() or (body.transcript or "").strip()
    if not body_text and not body.audio_s3_key:
        from app.core.exceptions import ValidationError
        raise ValidationError(code="MISSING_BODY", message="Provide body_text, transcript, or audio_s3_key")
    async with UnitOfWork(factory) as uow:
        msg = await ingest_message(
            uow,
            current_user.id,
            connection_id=None,
            source_type="manual",
            sender_raw=None,
            direction="outbound",
            body_raw=body_text or body.transcript,
            message_type="voice_note" if body.audio_s3_key else "manual_note",
            sent_at=utcnow(),
        )
        if msg and body.audio_s3_key:
            await uow.messages.update(msg, audio_s3_key=body.audio_s3_key, transcript=body.transcript)
            await uow.session.refresh(msg)
    if not msg:
        from app.core.exceptions import ValidationError
        raise ValidationError(code="INGEST_FAILED", message="Failed to create manual note")
    log.info("messages.manual_created", user_id=str(current_user.id), message_id=str(msg.id))
    return message_to_response(msg)

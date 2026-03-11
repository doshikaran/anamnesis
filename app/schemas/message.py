"""Message and thread request/response schemas. API boundary only."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """Message as returned to client."""

    id: str
    user_id: str
    source_type: str
    external_id: str | None
    thread_id: str | None
    db_thread_id: str | None
    sender_person_id: str | None
    sender_raw: str | None
    direction: str
    subject: str | None
    body_clean: str | None
    body_summary: str | None
    message_type: str
    sent_at: datetime
    received_at: datetime | None
    created_at: datetime
    has_commitment: bool = False
    importance_score: float | None = None

    model_config = {"from_attributes": True}


class MessageSearchParams(BaseModel):
    """Query params for GET /messages search."""

    q: str | None = None
    person_id: UUID | None = None
    source_type: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ThreadResponse(BaseModel):
    """Thread in list or with message count."""

    id: str
    user_id: str
    connection_id: str | None
    source_type: str
    external_thread_id: str | None
    subject: str | None
    message_count: int = 0
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ThreadDetailResponse(ThreadResponse):
    """Thread with messages array."""

    messages: list[MessageResponse] = []


class ManualNoteCreateSchema(BaseModel):
    """Body for POST /messages/manual (manual note or voice)."""

    body_text: str | None = None
    audio_s3_key: str | None = None
    transcript: str | None = None


def message_to_response(m: "Message") -> MessageResponse:  # noqa: F821
    """Map Message ORM to MessageResponse."""
    return MessageResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        source_type=m.source_type,
        external_id=m.external_id,
        thread_id=m.thread_id,
        db_thread_id=str(m.db_thread_id) if m.db_thread_id else None,
        sender_person_id=str(m.sender_person_id) if m.sender_person_id else None,
        sender_raw=m.sender_raw,
        direction=m.direction,
        subject=m.subject,
        body_clean=m.body_clean,
        body_summary=m.body_summary,
        message_type=m.message_type,
        sent_at=m.sent_at,
        received_at=m.received_at,
        created_at=m.created_at,
        has_commitment=m.has_commitment or False,
        importance_score=m.importance_score,
    )


def thread_to_response(t: "Thread") -> ThreadResponse:  # noqa: F821
    """Map Thread ORM to ThreadResponse."""
    return ThreadResponse(
        id=str(t.id),
        user_id=str(t.user_id),
        connection_id=str(t.connection_id) if t.connection_id else None,
        source_type=t.source_type,
        external_thread_id=t.external_thread_id,
        subject=t.subject,
        message_count=t.message_count or 0,
        last_message_at=t.last_message_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )

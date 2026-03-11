"""Person request/response schemas. API boundary only."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


RELATIONSHIP_TYPES = Literal[
    "family", "close_friend", "friend", "colleague",
    "client", "manager", "report", "acquaintance", "contact",
]


class PersonResponse(BaseModel):
    """Person in list/detail. No PII beyond what user sees."""

    id: str
    user_id: str
    display_name: str
    first_name: str | None
    last_name: str | None
    canonical_email: str | None
    relationship_type: str
    relationship_label: str | None
    importance_score: float
    is_starred: bool
    last_contact_at: datetime | None
    last_outbound_at: datetime | None
    last_inbound_at: datetime | None
    sources: list[str] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonDetailResponse(PersonResponse):
    """Full person profile including known_facts, life_events, open_topics (if needed)."""

    all_emails: list[str] | None = None
    phone_numbers: list[str] | None = None
    avatar_url: str | None = None
    avg_response_days: float | None = None
    contact_frequency: str | None = None
    sentiment_score: float | None = None
    sentiment_trend: str | None = None
    known_facts: list | None = None
    life_events: list | None = None
    open_topics: list | None = None


class PersonUpdateSchema(BaseModel):
    """Update relationship_type, label, starred."""

    relationship_type: RELATIONSHIP_TYPES | None = None
    relationship_label: str | None = None
    is_starred: bool | None = None
    display_name: str | None = None


class RelationshipTimelineItem(BaseModel):
    """Single message or event in a person's timeline."""

    id: str
    type: Literal["message", "event"]
    subject: str | None = None
    body_preview: str | None = None
    sent_at: datetime | None = None
    event_date: str | None = None
    event_type: str | None = None
    description: str | None = None


class MergeRequestSchema(BaseModel):
    """Body for POST /people/merge."""

    primary_id: UUID
    secondary_id: UUID


def person_to_response(p: "Person") -> PersonResponse:  # noqa: F821
    """Map Person ORM to PersonResponse."""
    return PersonResponse(
        id=str(p.id),
        user_id=str(p.user_id),
        display_name=p.display_name,
        first_name=p.first_name,
        last_name=p.last_name,
        canonical_email=p.canonical_email,
        relationship_type=p.relationship_type,
        relationship_label=p.relationship_label,
        importance_score=p.importance_score or 0.5,
        is_starred=p.is_starred or False,
        last_contact_at=p.last_contact_at,
        last_outbound_at=p.last_outbound_at,
        last_inbound_at=p.last_inbound_at,
        sources=p.sources,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def person_to_detail_response(p: "Person") -> PersonDetailResponse:  # noqa: F821
    """Map Person ORM to PersonDetailResponse."""
    base = person_to_response(p)
    return PersonDetailResponse(
        **base.model_dump(),
        all_emails=p.all_emails,
        phone_numbers=p.phone_numbers,
        avatar_url=p.avatar_url,
        avg_response_days=p.avg_response_days,
        contact_frequency=p.contact_frequency,
        sentiment_score=p.sentiment_score,
        sentiment_trend=p.sentiment_trend,
        known_facts=p.known_facts,
        life_events=p.life_events,
        open_topics=p.open_topics,
    )

"""
Pure Python domain objects for person/relationship logic. No SQLAlchemy, no Pydantic.
Used inside services and AI layer.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class PersonDomain:
    """Internal representation of a person for business logic."""

    id: UUID
    user_id: UUID
    display_name: str
    first_name: str | None
    last_name: str | None
    canonical_email: str | None
    all_emails: list[str]
    relationship_type: str
    importance_score: float
    is_starred: bool
    last_contact_at: datetime | None
    sources: list[str]
    external_ids: dict[str, str]


@dataclass
class ResolvedPerson:
    """Result of person resolution: either matched existing or data to create new."""

    person_id: UUID | None  # None if new
    display_name: str
    email: str | None
    source: str
    external_id: str | None
    confidence: float  # 0..1


@dataclass
class MergeCandidate:
    """A pair of people that may be duplicates for merge review."""

    person_a_id: UUID
    person_b_id: UUID
    display_name_a: str
    display_name_b: str
    email_overlap: bool
    name_similarity: float
    combined_confidence: float

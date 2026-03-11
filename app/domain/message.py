"""
Pure Python domain objects for message ingestion and processing. No SQLAlchemy, no Pydantic.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class SenderInfo:
    """Parsed sender: name and/or email from From header."""

    raw: str
    name: str | None
    email: str | None


@dataclass
class ParsedMessage:
    """Raw message as parsed from a connector (e.g. Gmail). Before cleaning and dedup."""

    external_id: str | None
    thread_id: str | None
    sender: SenderInfo
    recipients_raw: list[str]
    direction: str  # inbound | outbound | internal
    subject: str | None
    body_raw: str
    message_type: str
    sent_at: datetime
    received_at: datetime | None
    source_type: str


@dataclass
class CleanedMessage:
    """Message after body cleaning and content hash. Ready for dedup and persist."""

    external_id: str | None
    thread_id: str | None
    sender_raw: str | None
    direction: str
    subject: str | None
    body_raw: str
    body_clean: str
    content_hash: str | None
    message_type: str
    sent_at: datetime
    received_at: datetime | None
    source_type: str

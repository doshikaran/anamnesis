"""
Domain events and EventBus. When important things happen, fire events.
Subscribers (e.g. Celery tasks) react. Decouples ingestion from analysis from notification.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Type, TypeVar
from uuid import UUID


class DomainEvent:
    """Base for all domain events."""

    pass


@dataclass
class MessageIngested(DomainEvent):
    message_id: UUID
    user_id: UUID
    source_type: str
    has_potential_commitment: bool


@dataclass
class CommitmentCreated(DomainEvent):
    commitment_id: UUID
    user_id: UUID
    deadline_at: datetime | None
    person_id: UUID | None


@dataclass
class RelationshipSilenceDetected(DomainEvent):
    user_id: UUID
    person_id: UUID
    days_silent: int


@dataclass
class InsightGenerated(DomainEvent):
    insight_id: UUID
    user_id: UUID
    insight_type: str


EventT = TypeVar("EventT", bound=DomainEvent)


class EventBus:
    """Dispatches domain events to registered handlers (e.g. Celery task triggers)."""

    _handlers: dict[Type[DomainEvent], list[Callable[[DomainEvent], object]]] = {}

    @classmethod
    def subscribe(cls, event_type: Type[EventT], handler: Callable[[EventT], object]) -> None:
        cls._handlers.setdefault(event_type, []).append(handler)  # type: ignore[arg-type]

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        for handler in cls._handlers.get(type(event), []):
            result = handler(event)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]

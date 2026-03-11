"""
Unit of Work pattern. All DB writes in a service happen in a single transaction.
Atomicity: if any step fails, entire transaction rolls back.
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.base import BaseRepository
from app.repositories.commitment_repository import CommitmentRepository
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.insight_repository import InsightRepository
from app.repositories.relationship_event_repository import RelationshipEventRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.people_repository import PeopleRepository
from app.repositories.thread_repository import ThreadRepository
from app.repositories.user_repository import UserRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.query_repository import QueryRepository
from app.repositories.usage_repository import UsageRepository
from app.models.user import User
from app.models.connection import Connection
from app.models.person import Person
from app.models.thread import Thread
from app.models.message import Message
from app.models.commitment import Commitment
from app.models.insight import Insight
from app.models.notification import Notification
from app.models.query import Query
from app.models.ingestion_job import IngestionJob
from app.models.relationship_event import RelationshipEvent
from app.models.usage_event import UsageEvent


class UnitOfWork:
    """Single transaction scope with all repositories. Use async with."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.session: AsyncSession | None = None
        self.users: UserRepository | None = None
        self.connections: ConnectionRepository | None = None
        self.people: PeopleRepository | None = None
        self.threads: ThreadRepository | None = None
        self.messages: MessageRepository | None = None
        self.commitments: CommitmentRepository | None = None
        self.insights: InsightRepository | None = None
        self.relationship_events: RelationshipEventRepository | None = None
        self.notifications: NotificationRepository | None = None
        self.queries: QueryRepository | None = None
        self.ingestion_jobs: IngestionJobRepository | None = None
        self.usage: UsageRepository | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.session_factory()
        self.users = UserRepository(self.session, User)
        self.connections = ConnectionRepository(self.session, Connection)
        self.people = PeopleRepository(self.session, Person)
        self.threads = ThreadRepository(self.session, Thread)
        self.messages = MessageRepository(self.session, Message)
        self.commitments = CommitmentRepository(self.session, Commitment)
        self.insights = InsightRepository(self.session, Insight)
        self.relationship_events = RelationshipEventRepository(self.session, RelationshipEvent)
        self.notifications = NotificationRepository(self.session, Notification)
        self.queries = QueryRepository(self.session, Query)
        self.ingestion_jobs = IngestionJobRepository(self.session, IngestionJob)
        self.usage = UsageRepository(self.session, UsageEvent)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.session is None:
            return
        if exc_type is not None:
            await self.session.rollback()
        else:
            await self.session.commit()
        await self.session.close()
        self.session = None

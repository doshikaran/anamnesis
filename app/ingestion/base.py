"""
Ingestion base: BaseConnector ABC, SyncResult, connector registry, get_connector factory.
Every data-source connector implements BaseConnector. Pipeline uses only this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type
from uuid import UUID

if TYPE_CHECKING:
    from app.models.connection import Connection


@dataclass
class SyncResult:
    """Result of a full_sync or incremental_sync run."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


class BaseConnector(ABC):
    """
    Every connector implements this contract.
    Receives connection (with decrypted tokens when used by sync task).
    """

    def __init__(
        self,
        connection: "Connection",
        decrypted_access_token: str,
        decrypted_refresh_token: str,
    ):
        self.connection = connection
        self._access_token = decrypted_access_token
        self._refresh_token = decrypted_refresh_token

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Test if credentials are still valid."""

    @abstractmethod
    async def full_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        """Complete historical sync from sync_from_date (or default range)."""

    @abstractmethod
    async def incremental_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        """Sync only new items since last sync_cursor (e.g. Gmail historyId)."""

    @abstractmethod
    async def refresh_token_if_needed(self) -> bool:
        """Refresh OAuth token if expiring within 5 minutes. Return True if refreshed."""

    @abstractmethod
    def get_source_type(self) -> str:
        """Return the source_type string for this connector."""


# Registry: maps source_type to connector class. Populated when connectors are imported.
CONNECTOR_REGISTRY: dict[str, Type[BaseConnector]] = {}


def register_connector(source_type: str):
    """Decorator to register a connector class in CONNECTOR_REGISTRY."""

    def decorator(cls: Type[BaseConnector]) -> Type[BaseConnector]:
        CONNECTOR_REGISTRY[source_type] = cls
        return cls

    return decorator


def get_connector(
    connection: "Connection",
    decrypted_access_token: str,
    decrypted_refresh_token: str,
) -> BaseConnector:
    """Factory: return the right connector for this connection's source_type."""
    cls = CONNECTOR_REGISTRY.get(connection.source_type)
    if not cls:
        raise ValueError(f"Unknown source type: {connection.source_type}")
    return cls(connection, decrypted_access_token, decrypted_refresh_token)

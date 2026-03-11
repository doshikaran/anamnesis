"""Ingestion connectors. Import to register with CONNECTOR_REGISTRY."""

from app.ingestion.base import BaseConnector, SyncResult, get_connector, CONNECTOR_REGISTRY

# Register connectors (side effect)
from app.ingestion import gmail  # noqa: F401, E402
from app.ingestion import google_calendar  # noqa: F401, E402

__all__ = ["BaseConnector", "SyncResult", "get_connector", "CONNECTOR_REGISTRY"]

"""Connection request/response schemas. API boundary only."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


SOURCE_TYPES = Literal[
    "gmail",
    "google_calendar",
    "outlook_mail",
    "microsoft_calendar",
    "microsoft_teams",
    "slack",
    "notion",
    "imessage_bridge",
    "manual",
]

CONNECTION_STATUS = Literal["pending", "active", "paused", "error", "revoked"]


class ConnectionResponse(BaseModel):
    """Connection as returned to client. Never includes tokens."""

    id: str
    user_id: str
    source_type: str
    status: str
    display_name: str | None
    last_synced_at: datetime | None
    last_error: str | None
    error_count: int
    sync_enabled: bool
    sync_from_date: date | None
    sync_frequency_mins: int
    scopes: list[str] | None
    slack_team_name: str | None
    notion_workspace_name: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectionUpdateSchema(BaseModel):
    """Pause/resume/update connection."""

    sync_enabled: bool | None = None
    sync_frequency_mins: int | None = None
    display_name: str | None = None


class ConnectionCreateSchema(BaseModel):
    """Internal: create connection (e.g. after OAuth). Not used as API body."""

    user_id: UUID
    source_type: str
    access_token_encrypted: str
    refresh_token_encrypted: str
    token_expires_at: datetime | None
    scopes: list[str] | None = None
    display_name: str | None = None
    status: str = "active"


class IngestionJobResponse(BaseModel):
    """Ingestion job as returned to client."""

    id: str
    user_id: str
    connection_id: str | None
    job_type: str
    status: str
    total_items: int | None
    processed_items: int
    failed_items: int
    progress_pct: float
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    items_created: int
    items_updated: int
    items_skipped: int
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


def connection_to_response(conn) -> ConnectionResponse:
    """Map Connection ORM to ConnectionResponse (id as str, no tokens)."""
    return ConnectionResponse(
        id=str(conn.id),
        user_id=str(conn.user_id),
        source_type=conn.source_type,
        status=conn.status,
        display_name=conn.display_name,
        last_synced_at=conn.last_synced_at,
        last_error=conn.last_error,
        error_count=conn.error_count or 0,
        sync_enabled=conn.sync_enabled if conn.sync_enabled is not None else True,
        sync_from_date=conn.sync_from_date,
        sync_frequency_mins=conn.sync_frequency_mins or 30,
        scopes=conn.scopes,
        slack_team_name=conn.slack_team_name,
        notion_workspace_name=conn.notion_workspace_name,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def job_to_response(job) -> IngestionJobResponse:
    """Map IngestionJob ORM to IngestionJobResponse."""
    return IngestionJobResponse(
        id=str(job.id),
        user_id=str(job.user_id),
        connection_id=str(job.connection_id) if job.connection_id else None,
        job_type=job.job_type,
        status=job.status,
        total_items=job.total_items,
        processed_items=job.processed_items or 0,
        failed_items=job.failed_items or 0,
        progress_pct=job.progress_pct or 0.0,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_ms=job.duration_ms,
        items_created=job.items_created or 0,
        items_updated=job.items_updated or 0,
        items_skipped=job.items_skipped or 0,
        last_error=(
            job.error_log[-1].get("message")
            if job.error_log and isinstance(job.error_log[-1], dict)
            else None
        ),
        created_at=job.created_at,
    )

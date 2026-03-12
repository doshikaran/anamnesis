"""
Connections API: list, Google/Microsoft/Slack/Notion OAuth init+callback,
get/patch/delete connection, trigger sync, list jobs.
"""

import base64
import json
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_current_user, get_db, get_redis
from app.core.exceptions import NotFoundError, ValidationError
from app.models.user import User
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.models.connection import Connection
from app.schemas.connection import (
    ConnectionResponse,
    ConnectionUpdateSchema,
    IngestionJobResponse,
    connection_to_response,
    job_to_response,
)
from app.core.rate_limiter import rate_limit
from app.services.auth_service import save_connection_tokens
from app.workers.sync_tasks import sync_connection

router = APIRouter()
log = structlog.get_logger()
settings = get_settings()

# Scopes per source type (Google)
GOOGLE_SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile",
    "google_calendar": "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile",
}


def _encode_state(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def _decode_state(state: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(state.encode()).decode())
    except Exception:
        return {}


# ---------- Google connection OAuth ----------
@router.post("/google/init", dependencies=[rate_limit(5, 300, "connections_init")])
async def connections_google_init(
    request: Request,
    source_type: str = "gmail",
    current_user: User = Depends(get_current_user),
):
    """Start Google OAuth for adding Gmail or Google Calendar connection. Protected."""
    if source_type not in ("gmail", "google_calendar"):
        raise ValidationError(code="INVALID_SOURCE_TYPE", message="source_type must be gmail or google_calendar")
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/connections/google/callback"
    state = _encode_state({
        "user_id": str(current_user.id),
        "source_type": source_type,
        "redirect_uri": redirect_uri,
    })
    scope = GOOGLE_SCOPES.get(source_type, GOOGLE_SCOPES["gmail"])
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope={scope.replace(' ', '%20')}&state={state}&access_type=offline&prompt=consent"
    )
    return {"auth_url": auth_url}


@router.get("/google/callback")
async def connections_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Google OAuth callback for connections. Exchange code, save connection, redirect to frontend."""
    if error:
        log.warning("connections.google_callback_error", error=error)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=missing_code")
    data = _decode_state(state)
    user_id_str = data.get("user_id")
    source_type = data.get("source_type") or "gmail"
    if not user_id_str:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=invalid_state")
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=invalid_state")
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    import httpx

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/connections/google/callback"
    async with AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=redirect_uri,
    ) as client:
        token = await client.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
        )
    expires_at = token.get("expires_at")
    if isinstance(expires_at, (int, float)):
        from datetime import datetime, timezone
        token_expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    else:
        token_expires_at = None
    try:
        await save_connection_tokens(
            db,
            user_id,
            source_type=source_type,
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token") or "",
            token_expires_at=token_expires_at,
            scopes=token.get("scope", "").split() if isinstance(token.get("scope"), str) else None,
        )
    except Exception as e:
        log.exception("connections.google_save_failed", error=str(e))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=save_failed")
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?connected={source_type}")


# ---------- Microsoft (stub) ----------
@router.post("/microsoft/init")
async def connections_microsoft_init(
    request: Request,
    source_type: str = "outlook_mail",
    current_user: User = Depends(get_current_user),
):
    """Start Microsoft OAuth for Outlook/Teams/Calendar. Phase 8 full implementation."""
    raise ValidationError(code="NOT_IMPLEMENTED", message="Microsoft connection OAuth not yet implemented")


@router.get("/microsoft/callback")
async def connections_microsoft_callback(request: Request):
    """Microsoft OAuth callback. Phase 8."""
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=not_implemented")


# ---------- Slack ----------
SLACK_SCOPES = "channels:history,im:history,mpim:history,groups:history,users:read,team:read"


@router.post("/slack/init", dependencies=[rate_limit(5, 300, "connections_init")])
async def connections_slack_init(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Start Slack OAuth. Returns auth_url for redirect."""
    if not settings.SLACK_CLIENT_ID:
        raise ValidationError(code="OAUTH_NOT_CONFIGURED", message="Slack OAuth not configured")
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/connections/slack/callback"
    state = _encode_state({
        "user_id": str(current_user.id),
        "redirect_uri": redirect_uri,
    })
    auth_url = (
        "https://slack.com/oauth/v2/authorize"
        f"?client_id={settings.SLACK_CLIENT_ID}&scope={SLACK_SCOPES.replace(' ', '%20')}"
        f"&redirect_uri={redirect_uri}&state={state}"
    )
    return {"auth_url": auth_url}


@router.get("/slack/callback")
async def connections_slack_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Slack OAuth callback. Exchange code for bot token, save connection, redirect to frontend."""
    if error:
        log.warning("connections.slack_callback_error", error=error)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error={error}")
    if not code or not state:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=missing_code")
    data = _decode_state(state)
    user_id_str = data.get("user_id")
    if not user_id_str:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=invalid_state")
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=invalid_state")
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/connections/slack/callback"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        log.warning("connections.slack_token_failed", status_code=r.status_code)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=token_failed")
    body = r.json()
    if not body.get("ok"):
        log.warning("connections.slack_token_error", error=body.get("error"))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error={body.get('error', 'unknown')}")
    access_token = body.get("access_token") or ""
    team = body.get("team") or {}
    slack_team_id = team.get("id") or ""
    slack_team_name = team.get("name") or ""
    try:
        await save_connection_tokens(
            db,
            user_id,
            source_type="slack",
            access_token=access_token,
            refresh_token="",
            slack_team_id=slack_team_id,
            slack_team_name=slack_team_name,
            display_name=slack_team_name or "Slack",
        )
    except Exception as e:
        log.exception("connections.slack_save_failed", error=str(e))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=save_failed")
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?connected=slack")


# ---------- Notion (stub) ----------
@router.post("/notion/init")
async def connections_notion_init(current_user: User = Depends(get_current_user)):
    """Start Notion OAuth. Phase 8."""
    raise ValidationError(code="NOT_IMPLEMENTED", message="Notion connection not yet implemented")


@router.get("/notion/callback")
async def connections_notion_callback(request: Request):
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings/connections?error=not_implemented")


# ---------- iMessage (stub) ----------
@router.post("/imessage")
async def connections_imessage_register(current_user: User = Depends(get_current_user)):
    """Register iMessage bridge. Phase 8."""
    raise ValidationError(code="NOT_IMPLEMENTED", message="iMessage bridge not yet implemented")


# ---------- CRUD ----------
@router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all connections for the current user."""
    repo = ConnectionRepository(db, Connection)
    connections = await repo.list_by_user(current_user.id)
    return [connection_to_response(c) for c in connections]


@router.get("/{id}", response_model=ConnectionResponse)
async def get_connection(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single connection by id (must belong to current user)."""
    repo = ConnectionRepository(db, Connection)
    conn = await repo.get_by_id_and_user(id, current_user.id)
    if not conn:
        raise NotFoundError(code="CONNECTION_NOT_FOUND", message="Connection not found")
    return connection_to_response(conn)


@router.patch("/{id}", response_model=ConnectionResponse)
async def update_connection(
    id: UUID,
    body: ConnectionUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause/resume or update connection settings."""
    repo = ConnectionRepository(db, Connection)
    conn = await repo.get_by_id_and_user(id, current_user.id)
    if not conn:
        raise NotFoundError(code="CONNECTION_NOT_FOUND", message="Connection not found")
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await repo.update(conn, **updates)
        await db.flush()
    return connection_to_response(conn)


@router.delete("/{id}", status_code=204)
async def delete_connection(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke and delete connection."""
    repo = ConnectionRepository(db, Connection)
    conn = await repo.get_by_id_and_user(id, current_user.id)
    if not conn:
        raise NotFoundError(code="CONNECTION_NOT_FOUND", message="Connection not found")
    await db.delete(conn)
    await db.flush()


@router.post("/{id}/sync", dependencies=[rate_limit(2, 60, "connections_sync")])
async def trigger_sync(
    id: UUID,
    full_sync: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger manual sync for this connection. Queues Celery task."""
    repo = ConnectionRepository(db, Connection)
    conn = await repo.get_by_id_and_user(id, current_user.id)
    if not conn:
        raise NotFoundError(code="CONNECTION_NOT_FOUND", message="Connection not found")
    job_type = "full_sync" if full_sync else "incremental"
    task = sync_connection.delay(str(conn.id), job_type=job_type)
    log.info("connections.sync_triggered", connection_id=str(id), job_type=job_type, task_id=task.id)
    return {"message": "Sync queued", "task_id": task.id}


@router.get("/{id}/jobs", response_model=list[IngestionJobResponse])
async def list_connection_jobs(
    id: UUID,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List ingestion jobs for this connection."""
    repo = ConnectionRepository(db, Connection)
    conn = await repo.get_by_id_and_user(id, current_user.id)
    if not conn:
        raise NotFoundError(code="CONNECTION_NOT_FOUND", message="Connection not found")
    from app.models.ingestion_job import IngestionJob
    job_repo = IngestionJobRepository(db, IngestionJob)
    jobs = await job_repo.list_by_connection(conn.id, limit=limit)
    return [job_to_response(j) for j in jobs]

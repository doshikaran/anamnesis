"""
Insights API: list, get, mark read, dismiss.
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.insight import Insight
from app.repositories.insight_repository import InsightRepository

router = APIRouter()
log = structlog.get_logger()


def _insight_to_item(i: Insight) -> dict:
    return {
        "id": str(i.id),
        "insight_type": i.insight_type,
        "title": i.title,
        "body": i.body,
        "summary": i.summary,
        "person_ids": [str(x) for x in (i.person_ids or [])],
        "commitment_ids": [str(x) for x in (i.commitment_ids or [])],
        "importance_score": i.importance_score,
        "is_actionable": i.is_actionable or False,
        "suggested_action": i.suggested_action,
        "status": i.status or "unread",
        "read_at": i.read_at.isoformat() if i.read_at else None,
        "acted_at": i.acted_at.isoformat() if i.acted_at else None,
        "dismissed_at": i.dismissed_at.isoformat() if i.dismissed_at else None,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


@router.get("")
async def list_insights(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    insight_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
):
    """List insights for the current user with optional type/status filter and cursor pagination."""
    repo = InsightRepository(db, Insight)
    items, next_cursor = await repo.list_by_user(
        current_user.id,
        insight_type=insight_type,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    return {
        "items": [_insight_to_item(i) for i in items],
        "next_cursor": next_cursor,
    }


@router.get("/{id}")
async def get_insight(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single insight by id."""
    repo = InsightRepository(db, Insight)
    insight = await repo.get_by_id_and_user(id, current_user.id)
    if not insight:
        raise NotFoundError(code="INSIGHT_NOT_FOUND", message="Insight not found")
    return _insight_to_item(insight)


@router.patch("/{id}")
async def update_insight(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    read: bool | None = Query(None),
    dismiss: bool | None = Query(None),
):
    """Mark insight as read and/or dismissed."""
    repo = InsightRepository(db, Insight)
    insight = await repo.get_by_id_and_user(id, current_user.id)
    if not insight:
        raise NotFoundError(code="INSIGHT_NOT_FOUND", message="Insight not found")
    now = datetime.now(timezone.utc)
    updates = {}
    if read is True and not insight.read_at:
        updates["read_at"] = now
        updates["status"] = "read"
    if dismiss is True and not insight.dismissed_at:
        updates["dismissed_at"] = now
        updates["status"] = "dismissed"
    if updates:
        await repo.update(insight, **updates)
        await db.refresh(insight)
    return _insight_to_item(insight)

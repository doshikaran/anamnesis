"""
Phase 7: Generate daily morning briefing (summary of people, commitments, recent activity).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.core.unit_of_work import UnitOfWork

import structlog

from app.ai.client import call_claude, MODEL_HAIKU
from app.ai.query_engine import build_user_context

log = structlog.get_logger()

BRIEFING_SYSTEM = """You are a concise morning briefing assistant. Given the user's relationship context (top people, open commitments, recent activity), produce a SHORT daily briefing.

Output exactly two lines, separated by a newline:
Line 1: A one-line headline (e.g. "3 open commitments, 2 people you haven't contacted in a week").
Line 2: A single actionable sentence (e.g. "Consider following up with Sarah on the proposal.").

Keep the headline under 80 characters and the sentence under 120 characters. Be warm and practical."""


async def generate_daily_briefing(uow: "UnitOfWork", user_id: UUID) -> tuple[str, str]:
    """
    Build user context and generate title + body for the user's morning briefing.
    Returns (title, body).
    """
    context = await build_user_context(uow, user_id)
    user_msg = f"Context:\n{context}\n\nGenerate the two-line briefing (headline, then sentence)."
    messages = [{"role": "user", "content": user_msg}]

    raw = await call_claude(
        messages,
        model=MODEL_HAIKU,
        system=BRIEFING_SYSTEM,
        user_id=user_id,
        event_type="briefing",
        usage_repo=uow.usage,
        max_tokens=256,
    )
    lines = [ln.strip() for ln in (raw or "").strip().split("\n") if ln.strip()]
    title = lines[0][:200] if lines else "Your daily briefing"
    body = lines[1][:500] if len(lines) > 1 else "Check your commitments and contacts today."
    return title, body

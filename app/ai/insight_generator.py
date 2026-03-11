"""
Phase 7: Generate insights (e.g. relationship silence). Creates Insight record and optional Notification.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.core.unit_of_work import UnitOfWork

import structlog

from app.ai.client import call_claude, MODEL_HAIKU
from app.core.events import EventBus, InsightGenerated

log = structlog.get_logger()

INSIGHT_SILENCE_SYSTEM = """You generate a short, friendly insight for the user about a relationship that has gone quiet.
Output JSON only, no markdown:
{
  "title": "Short headline (e.g. 'No contact with X in 7 days')",
  "body": "1-2 sentences suggesting they might want to reach out, with a light tone.",
  "summary": "One line for notifications (optional)"
}
Keep title under 60 chars, body under 200 chars."""


def _parse_json_block(raw: str) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def generate_insight_for_silence(
    uow: "UnitOfWork",
    user_id: UUID,
    person_id: UUID,
    days_silent: int,
) -> UUID | None:
    """
    Create a relationship_silence insight for (user, person) and optionally a pending push notification.
    Returns insight_id or None if skipped (e.g. person not found).
    """
    person = await uow.people.get_by_id_and_user(person_id, user_id)
    if not person:
        log.warning("insight_generator.person_not_found", user_id=str(user_id), person_id=str(person_id))
        return None

    name = person.display_name or person.first_name or "Someone"
    user_msg = f"Person: {name}. Days since last contact: {days_silent}. Generate the JSON insight."

    messages = [{"role": "user", "content": user_msg}]
    raw = await call_claude(
        messages,
        model=MODEL_HAIKU,
        system=INSIGHT_SILENCE_SYSTEM,
        user_id=user_id,
        event_type="insight_silence",
        usage_repo=uow.usage,
        max_tokens=256,
    )
    data = _parse_json_block(raw)
    if not data:
        log.warning("insight_generator.parse_failed", raw=raw[:200])
        title = f"No contact with {name} in {days_silent} days"
        body = f"You haven't been in touch with {name} recently. Consider saying hi."
        summary = title
    else:
        title = (data.get("title") or "").strip() or f"No contact with {name} in {days_silent} days"
        body = (data.get("body") or "").strip() or "Consider reaching out."
        summary = (data.get("summary") or "").strip() or title

    insight = await uow.insights.create(
        user_id=user_id,
        insight_type="relationship_silence",
        title=title[:500],
        body=body[:2000],
        summary=summary[:500] if summary else None,
        person_ids=[person_id],
        commitment_ids=None,
        message_ids=None,
        importance_score=0.6,
        is_actionable=True,
        suggested_action=f"Reach out to {name}",
        status="unread",
    )

    # Optional: create a pending push notification (dedup by key)
    notification_key = f"insight_silence:{user_id}:{person_id}"
    existing = await uow.notifications.get_by_notification_key(notification_key)
    if not existing:
        await uow.notifications.create(
            user_id=user_id,
            insight_id=insight.id,
            commitment_id=None,
            channel="push",
            title=title[:200],
            body=summary[:500] if summary else body[:500],
            action_url=None,
            status="pending",
            notification_key=notification_key,
        )

    await EventBus.publish(
        InsightGenerated(insight_id=insight.id, user_id=user_id, insight_type="relationship_silence")
    )
    log.info(
        "insight_generator.silence_created",
        insight_id=str(insight.id),
        user_id=str(user_id),
        person_id=str(person_id),
        days_silent=days_silent,
    )
    return insight.id

"""
Phase 5: AI analysis pipeline for a single message.
Orchestrates extraction, sentiment, commitment detection, embedding; updates message and creates commitments.
Idempotent: safe to re-run for the same message.
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
from app.ai.embeddings import embed_text
from app.ai.prompts import (
    SYSTEM_COMMITMENTS,
    SYSTEM_EXTRACTION,
    SYSTEM_SENTIMENT,
    build_commitments_user,
    build_extraction_user,
    build_sentiment_user,
)

log = structlog.get_logger()


def _parse_json_block(raw: str) -> dict[str, Any] | None:
    """Extract JSON from response; strip markdown code blocks if present."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    # Strip ```json ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def analyze_message(
    uow: "UnitOfWork",
    message_id: UUID,
) -> None:
    """
    Load message, run extraction + sentiment + commitments + embedding, update message, create commitments.
    Uses Claude Haiku for all LLM steps; OpenAI for embedding. Logs all usage.
    """
    from app.core.events import EventBus, CommitmentCreated

    msg = await uow.messages.get_by_id(message_id)
    if not msg:
        log.warning("analysis.message_not_found", message_id=str(message_id))
        return
    user_id = msg.user_id
    body = msg.body_clean or msg.body_raw or ""
    subject = msg.subject or ""
    sender_raw = msg.sender_raw or ""
    direction = msg.direction or "inbound"

    # Text blob for embedding (subject + body)
    text_for_embed = f"Subject: {subject}\n\n{body}".strip()

    # 1) Extraction: summary, topics, entities, has_question
    ext_user = build_extraction_user(subject, body)
    ext_json = await call_claude(
        [{"role": "user", "content": ext_user}],
        model=MODEL_HAIKU,
        system=SYSTEM_EXTRACTION,
        user_id=user_id,
        event_type="message_extraction",
        usage_repo=uow.usage,
        reference_id=message_id,
        reference_type="message",
        max_tokens=1024,
    )
    body_summary = None
    topics: list[str] | None = None
    entities_mentioned: list[dict] | None = None
    has_question = None
    if ext_json:
        data = _parse_json_block(ext_json)
        if data:
            body_summary = data.get("summary")
            if isinstance(data.get("topics"), list):
                topics = [str(t) for t in data["topics"][:10]]
            if isinstance(data.get("entities_mentioned"), list):
                entities_mentioned = [
                    {"type": str(e.get("type", "other")), "value": str(e.get("value", ""))}
                    for e in data["entities_mentioned"][:50]
                ]
            if "has_question" in data:
                has_question = bool(data["has_question"])

    # 2) Sentiment
    sent_user = build_sentiment_user(subject, body)
    sent_json = await call_claude(
        [{"role": "user", "content": sent_user}],
        model=MODEL_HAIKU,
        system=SYSTEM_SENTIMENT,
        user_id=user_id,
        event_type="message_sentiment",
        usage_repo=uow.usage,
        reference_id=message_id,
        reference_type="message",
        max_tokens=256,
    )
    sentiment_label = None
    sentiment_score = None
    if sent_json:
        data = _parse_json_block(sent_json)
        if data:
            sentiment_label = data.get("label")
            if "score" in data and data["score"] is not None:
                try:
                    sentiment_score = float(data["score"])
                except (TypeError, ValueError):
                    pass

    # 3) Commitments
    comm_user = build_commitments_user(sender_raw, subject, direction, body)
    comm_json = await call_claude(
        [{"role": "user", "content": comm_user}],
        model=MODEL_HAIKU,
        system=SYSTEM_COMMITMENTS,
        user_id=user_id,
        event_type="message_commitments",
        usage_repo=uow.usage,
        reference_id=message_id,
        reference_type="message",
        max_tokens=1024,
    )
    has_commitment = False
    commitments_payload: list[dict] = []
    if comm_json:
        data = _parse_json_block(comm_json)
        if data:
            has_commitment = bool(data.get("has_commitment"))
            if isinstance(data.get("commitments"), list):
                commitments_payload = data["commitments"]

    # 4) Embedding
    embedding = await embed_text(
        text_for_embed,
        user_id=user_id,
        usage_repo=uow.usage,
        event_type="message_embedding",
        reference_id=message_id,
        reference_type="message",
    )

    # 5) Update message
    await uow.messages.update(
        msg,
        body_summary=body_summary,
        topics=topics,
        entities_mentioned=entities_mentioned or [],
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        has_commitment=has_commitment,
        has_question=has_question,
        embedding=embedding,
    )

    # 6) Create commitment records and publish CommitmentCreated
    for c in commitments_payload:
        desc = (c.get("description") or "").strip() or (c.get("raw_text") or "").strip()
        if not desc:
            continue
        raw_text = c.get("raw_text")
        dir_val = (c.get("direction") or "outbound").lower()
        if dir_val not in ("inbound", "outbound"):
            dir_val = "outbound"
        deadline_raw = c.get("deadline_raw")
        deadline_type = c.get("deadline_type")
        confidence = c.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None

        person_id = msg.sender_person_id if dir_val == "inbound" else (msg.recipient_person_ids or [None])[0]
        person_name_raw = None  # Could set from message context if needed

        commitment = await uow.commitments.create(
            user_id=user_id,
            description=desc[:2000],
            raw_text=raw_text[:2000] if raw_text else None,
            commitment_type="promise",
            direction=dir_val,
            person_id=person_id,
            person_name_raw=person_name_raw,
            source_message_id=msg.id,
            source_thread_id=msg.db_thread_id,
            source_type=msg.source_type,
            deadline_at=None,  # Phase 5: no NLP date parsing yet
            deadline_raw=deadline_raw[:500] if deadline_raw else None,
            deadline_type=deadline_type,
            deadline_confidence=confidence,
            status="open",
            extraction_confidence=confidence,
        )
        await EventBus.publish(
            CommitmentCreated(
                commitment_id=commitment.id,
                user_id=user_id,
                deadline_at=commitment.deadline_at,
                person_id=commitment.person_id,
            )
        )

    log.info(
        "analysis.message_done",
        message_id=str(message_id),
        has_commitment=has_commitment,
        commitments_created=len(commitments_payload),
    )

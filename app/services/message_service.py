"""
Message service: ingest_message (clean → dedup → resolve people → create thread → save → fire event).
Uses repositories and people_service for resolution. No raw SQL in business logic.
"""

from datetime import datetime, timezone
from uuid import UUID
from typing import TYPE_CHECKING

from app.core.events import EventBus, MessageIngested
from app.utils.text import clean_message_body
from app.utils.hashing import content_hash
from app.utils.email_utils import parse_email_address, normalize_email
from app.services.people_service import resolve_or_create_person, update_contact_stats

if TYPE_CHECKING:
    from app.core.unit_of_work import UnitOfWork
    from app.domain.message import ParsedMessage, CleanedMessage


async def ingest_message(
    uow: "UnitOfWork",
    user_id: UUID,
    connection_id: UUID | None,
    source_type: str,
    *,
    external_id: str | None = None,
    thread_id: str | None = None,
    sender_raw: str | None = None,
    recipients_raw: list[str] | None = None,
    direction: str = "inbound",
    subject: str | None = None,
    body_raw: str | None = None,
    message_type: str = "email",
    sent_at: datetime | None = None,
) -> "Message | None":
    """
    Full pipeline: clean body, dedup by external_id or content_hash, resolve sender (and recipients),
    get_or_create thread, create message, update contact stats, fire MessageIngested event.
    Returns created Message or None if skipped (duplicate).
    """
    from app.models.message import Message

    body_clean = clean_message_body(body_raw) if body_raw else ""
    content_hash_val = content_hash(body_clean)
    sent_at = sent_at or datetime.now(timezone.utc)

    # Dedup: by external_id first, then by content_hash
    if external_id and source_type:
        existing = await uow.messages.get_by_external_id(user_id, source_type, external_id)
        if existing:
            return None
    if content_hash_val:
        existing = await uow.messages.get_by_content_hash(user_id, content_hash_val)
        if existing:
            return None

    # Resolve sender to person (skip if no sender_raw, e.g. manual note)
    sender_person_id = None
    if sender_raw:
        parsed = parse_email_address(sender_raw)
        sender_email = normalize_email(parsed.email) if parsed else None
        sender_name = (parsed.name or "").strip() if parsed else None
        if sender_email or sender_name:
            sender_person = await resolve_or_create_person(
                uow.people,
                user_id,
                email=sender_email,
                display_name=sender_name,
                source=source_type,
                external_id=None,
            )
            sender_person_id = sender_person.id if sender_person else None

    # Resolve recipients (optional; can be done in Phase 5)
    recipient_person_ids: list[UUID] = []
    if recipients_raw:
        for r in recipients_raw[:20]:
            p = parse_email_address(r)
            if p and p.email:
                recv_person = await resolve_or_create_person(
                    uow.people,
                    user_id,
                    email=p.email,
                    display_name=p.name,
                    source=source_type,
                )
                if recv_person and recv_person.id not in recipient_person_ids:
                    recipient_person_ids.append(recv_person.id)

    # Thread
    thread = None
    if thread_id:
        thread = await uow.threads.get_by_external(user_id, source_type, thread_id)
    if not thread:
        thread = await uow.threads.create(
            user_id=user_id,
            connection_id=connection_id,
            source_type=source_type,
            external_thread_id=thread_id,
            subject=subject,
        )

    # Create message
    msg = await uow.messages.create(
        user_id=user_id,
        connection_id=connection_id,
        source_type=source_type,
        external_id=external_id,
        thread_id=thread_id,
        db_thread_id=thread.id,
        sender_person_id=sender_person_id,
        sender_raw=sender_raw,
        recipient_person_ids=recipient_person_ids if recipient_person_ids else None,
        recipients_raw=recipients_raw,
        direction=direction,
        subject=subject,
        body_raw=(body_clean[:50000] if body_clean else None),
        body_clean=(body_clean[:50000] if body_clean else None),
        content_hash=content_hash_val,
        message_type=message_type,
        sent_at=sent_at,
    )

    # Update contact stats for sender
    if sender_person_id:
        if direction == "outbound":
            await update_contact_stats(uow.people, sender_person_id, user_id, last_contact_at=sent_at, last_outbound_at=sent_at)
        else:
            await update_contact_stats(uow.people, sender_person_id, user_id, last_contact_at=sent_at, last_inbound_at=sent_at)

    # Fire event for downstream (e.g. analyze_message task)
    await EventBus.publish(MessageIngested(message_id=msg.id, user_id=user_id, source_type=source_type, has_potential_commitment=False))

    return msg

"""
Phase 6: Query engine. Hybrid search (pgvector + filters), intent parsing, streaming answers.
Prompt caching: user context (top people, open commitments, recent activity) as system prefix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from app.ai.client import MODEL_HAIKU, MODEL_SONNET, call_claude, stream_claude
from app.ai.embeddings import embed_text

if TYPE_CHECKING:
    from app.core.unit_of_work import UnitOfWork

log = structlog.get_logger()

# Intent types for routing
INTENT_SEARCH = "search"       # find something (use Haiku + hybrid search)
INTENT_DRAFT = "draft"         # write email/message (Sonnet)
INTENT_SUMMARIZE = "summarize" # summarize relationship/thread (Sonnet)
INTENT_ASK = "ask"             # general question about life/patterns (Sonnet)

INTENT_SYSTEM = """You classify the user's query into exactly one intent. Output valid JSON only.
Intent must be one of: "search", "draft", "summarize", "ask".

- search: find messages, commitments, or facts (e.g. "when did I last email John?", "messages about project X").
- draft: compose or write something (e.g. "draft a reply", "write an email to Jane").
- summarize: summarize a relationship, thread, or time period (e.g. "summarize my conversations with Alex", "what happened last week with the team?").
- ask: general question about patterns, life, or advice (e.g. "who do I neglect?", "am I overcommitting?").

Output: {"intent": "<one of search|draft|summarize|ask>", "person_name": "<extracted name or null>", "date_ref": "<e.g. last week or null>"}
Output only the JSON object. No markdown."""

CONTEXT_SYSTEM_PREFIX = """You are a helpful assistant for the user's personal relationship and commitment data. Use the following context about the user when answering. This context is cached for cost optimization.

{context}

Answer concisely and accurately. When citing messages or people, be specific."""


@dataclass
class ResolvedIntent:
    intent: str
    person_name: str | None
    date_ref: str | None


@dataclass
class QueryResult:
    """Result of running the query pipeline (before streaming)."""
    intent: ResolvedIntent
    source_message_ids: list[UUID]
    source_person_ids: list[UUID]
    model_used: str
    system_prefix: str
    user_message: str


def _parse_intent_json(raw: str) -> dict[str, Any] | None:
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


async def build_user_context(uow: "UnitOfWork", user_id: UUID) -> str:
    """
    Build user's personal context summary: top 20 people + open commitments count + recent activity.
    Used as cached system prompt prefix for cost optimization.
    """
    # Top 20 people (by recent contact; importance could be used instead)
    people = await uow.people.list_by_user(user_id, limit=20)
    people_lines = []
    for p in people[:20]:
        name = p.display_name or p.first_name or "(unknown)"
        last = p.last_contact_at
        last_str = last.strftime("%Y-%m-%d") if last else "never"
        people_lines.append(f"- {name} (last contact: {last_str})")
    people_blob = "\n".join(people_lines) if people_lines else "No contacts yet."

    # Open commitments count
    open_commitments = await uow.commitments.list_by_user(user_id, status="open", limit=500)
    open_count = len(open_commitments)

    # Recent activity: last 5 messages (subject/summary)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await uow.messages.list_search(user_id, from_date=week_ago, limit=5)
    activity_lines = []
    for m in recent:
        subj = (m.subject or "(no subject)")[:60]
        summary = (m.body_summary or "")[:80]
        activity_lines.append(f"- {subj} | {summary}")
    activity_blob = "\n".join(activity_lines) if activity_lines else "No recent messages."

    return f"""Top people (recent contacts):
{people_blob}

Open commitments count: {open_count}

Recent activity (last 7 days):
{activity_blob}"""


async def parse_intent(uow: "UnitOfWork", user_id: UUID, query_text: str) -> ResolvedIntent:
    """Classify query into search, draft, summarize, or ask. Extract person_name and date_ref if present."""
    messages = [{"role": "user", "content": f"Query: {query_text[:1000]}"}]
    raw = await call_claude(
        messages,
        model=MODEL_HAIKU,
        system=INTENT_SYSTEM,
        user_id=user_id,
        event_type="query_intent",
        usage_repo=uow.usage,
        max_tokens=128,
    )
    data = _parse_intent_json(raw)
    if not data:
        return ResolvedIntent(intent=INTENT_SEARCH, person_name=None, date_ref=None)
    intent = (data.get("intent") or "search").strip().lower()
    if intent not in (INTENT_SEARCH, INTENT_DRAFT, INTENT_SUMMARIZE, INTENT_ASK):
        intent = INTENT_SEARCH
    return ResolvedIntent(
        intent=intent,
        person_name=data.get("person_name") or None,
        date_ref=data.get("date_ref") or None,
    )


async def hybrid_search_messages(
    uow: "UnitOfWork",
    user_id: UUID,
    query_text: str,
    *,
    person_id: UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    has_commitment: bool | None = None,
    limit: int = 20,
) -> tuple[list[Any], list[UUID], list[UUID]]:
    """
    Embed query, run hybrid search (pgvector + filters). Returns (messages, message_ids, person_ids).
    """
    # Embed query (don't log to usage_events here; query row will log overall)
    embedding = await embed_text(
        query_text,
        user_id=user_id,
        usage_repo=uow.usage,
        event_type="query_embedding",
        max_chars=2000,
    )
    if not embedding:
        # Fallback: filter-only search
        messages = await uow.messages.list_search(
            user_id,
            person_id=person_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    else:
        messages = await uow.messages.hybrid_search(
            user_id,
            embedding,
            person_id=person_id,
            from_date=from_date,
            to_date=to_date,
            has_commitment=has_commitment,
            limit=limit,
        )

    msg_ids = [m.id for m in messages]
    person_ids: list[UUID] = []
    seen: set[UUID] = set()
    for m in messages:
        if m.sender_person_id and m.sender_person_id not in seen:
            seen.add(m.sender_person_id)
            person_ids.append(m.sender_person_id)
        for r in (m.recipient_person_ids or []):
            if r and r not in seen:
                seen.add(r)
                person_ids.append(r)
    return (messages, msg_ids, person_ids)


async def run_query(
    uow: "UnitOfWork",
    user_id: UUID,
    query_text: str,
) -> QueryResult:
    """
    Parse intent, resolve filters, run hybrid search when intent is search,
    build system prompt with cached context, select model (Haiku for search, Sonnet for rest).
    Returns QueryResult with system_prefix and user_message for streaming.
    """
    intent = await parse_intent(uow, user_id, query_text)
    context = await build_user_context(uow, user_id)
    system_prefix = CONTEXT_SYSTEM_PREFIX.format(context=context)

    source_message_ids: list[UUID] = []
    source_person_ids: list[UUID] = []
    from_date: datetime | None = None
    to_date: datetime | None = None
    person_id: UUID | None = None

    # Resolve person from intent
    if intent.person_name:
        people = await uow.people.search_by_name_trigram(user_id, intent.person_name, limit=1)
        if people:
            person_id = people[0].id
            source_person_ids.append(person_id)

    # Optional: resolve date_ref to from_date/to_date (simplified: last 7 days if "last week")
    if intent.date_ref and "week" in intent.date_ref.lower():
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=7)
        to_date = now

    if intent.intent == INTENT_SEARCH:
        model = MODEL_HAIKU
        messages, source_message_ids, person_ids = await hybrid_search_messages(
            uow, user_id, query_text,
            person_id=person_id,
            from_date=from_date,
            to_date=to_date,
            limit=15,
        )
        source_person_ids = list(set(source_person_ids) | set(person_ids))
        # Build user message with retrieved snippets
        snippets = []
        for m in messages[:15]:
            s = f"[{m.sent_at.date() if m.sent_at else '?'}] "
            s += (m.subject or "(no subject)")[:80]
            if m.body_summary:
                s += " | " + (m.body_summary[:150] or "")
            snippets.append(s)
        context_block = "\n".join(snippets) if snippets else "No matching messages found."
        user_message = f"""Based on the following retrieved messages, answer the user's question. If the answer is not in the messages, say so.

Retrieved messages:
{context_block}

User question: {query_text}"""
    else:
        model = MODEL_SONNET
        # For draft/summarize/ask, optionally pull in recent messages for context
        messages, source_message_ids, person_ids = await hybrid_search_messages(
            uow, user_id, query_text,
            person_id=person_id,
            from_date=from_date,
            to_date=to_date,
            limit=10,
        )
        source_person_ids = list(set(source_person_ids) | set(person_ids))
        snippets = []
        for m in messages[:10]:
            snippets.append(f"- [{m.sent_at.date() if m.sent_at else '?'}] {(m.subject or '(no subject)')[:60]}: {(m.body_summary or '')[:100]}")
        context_block = "\n".join(snippets) if snippets else "No specific messages retrieved."
        user_message = f"""Relevant context from user's messages (if any):
{context_block}

User request: {query_text}"""

    return QueryResult(
        intent=intent,
        source_message_ids=source_message_ids,
        source_person_ids=source_person_ids,
        model_used=model,
        system_prefix=system_prefix,
        user_message=user_message,
    )

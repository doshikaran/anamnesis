"""
Queries API: POST /queries streams the answer via Server-Sent Events (text/event-stream).
Every query is logged to the queries table with tokens_used, cost_usd, latency_ms, model_used, source_message_ids.
"""

import json
import time
from collections.abc import AsyncGenerator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.ai.client import estimate_cost_usd, stream_claude
from app.ai.query_engine import QueryResult, run_query
from app.core.database import get_session_factory
from app.core.unit_of_work import UnitOfWork
from app.core.rate_limiter import rate_limit
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.query_schema import QueryCreateSchema, QueryResponseSchema

router = APIRouter()
log = structlog.get_logger()


async def _stream_sse_events(
    query_id: UUID,
    user_id: UUID,
    result: QueryResult,
    start_time: float,
) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events: event 'chunk' with data text, then event 'done' with usage."""
    full_text = ""
    usage_dict: dict | None = None

    messages = [{"role": "user", "content": result.user_message}]
    async for chunk, usage in stream_claude(
        messages,
        model=result.model_used,
        system=result.system_prefix,
        max_tokens=4096,
        use_system_cache=True,  # Cache user context (top people, commitments, recent activity)
        user_id=user_id,
        event_type="query_stream",
        usage_repo=None,  # We log to queries table only for this flow
        reference_id=query_id,
        reference_type="query",
    ):
        if chunk:
            full_text += chunk
            # SSE: escape newlines in data
            data = json.dumps({"text": chunk})
            yield f"event: chunk\ndata: {data}\n\n"
        if usage is not None and "error" not in usage:
            usage_dict = usage

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_used = 0
    cost_usd = 0.0
    if usage_dict:
        tokens_used = (usage_dict.get("input_tokens") or 0) + (usage_dict.get("output_tokens") or 0)
        cost_usd = estimate_cost_usd(
            result.model_used,
            usage_dict.get("input_tokens", 0),
            usage_dict.get("output_tokens", 0),
            usage_dict.get("cache_creation_input_tokens", 0),
        )
    yield f"event: done\ndata: {json.dumps({'tokens_used': tokens_used, 'cost_usd': cost_usd, 'latency_ms': latency_ms})}\n\n"

    # Persist final response and usage to queries table
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        q = await uow.queries.get_by_id_and_user(query_id, user_id)
        if q:
            await uow.queries.update(
                q,
                response_text=full_text,
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                model_used=result.model_used,
                source_message_ids=result.source_message_ids,
                source_person_ids=result.source_person_ids[:50] if result.source_person_ids else None,
            )
            log.info(
                "query.saved",
                query_id=str(query_id),
                tokens_used=tokens_used,
                latency_ms=latency_ms,
            )


@router.post("", status_code=200, dependencies=[rate_limit(10, 60, "queries")])
async def create_query_stream(
    body: QueryCreateSchema,
    current_user: User = Depends(get_current_user),
):
    """
    Submit a natural language query. Streams the answer using Server-Sent Events (text/event-stream).
    Events: 'chunk' (data: {"text": "..."}), then 'done' (data: {"tokens_used", "cost_usd", "latency_ms"}).
    Query is logged to the queries table with intent, source_message_ids, model_used, tokens_used, cost_usd, latency_ms.
    """
    input_text = body.input_text.strip()
    if not input_text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="input_text required")

    start_time = time.perf_counter()
    factory = get_session_factory()

    async with UnitOfWork(factory) as uow:
        query = await uow.queries.create(
            user_id=current_user.id,
            input_text=input_text,
        )
        result = await run_query(uow, current_user.id, input_text)
        await uow.queries.update(
            query,
            intent=result.intent.intent,
            source_message_ids=result.source_message_ids,
            source_person_ids=result.source_person_ids[:50] if result.source_person_ids else None,
            model_used=result.model_used,
        )

    return StreamingResponse(
        _stream_sse_events(query.id, current_user.id, result, start_time),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[QueryResponseSchema])
async def list_queries(
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """List current user's query history (non-streaming)."""
    factory = get_session_factory()
    async with UnitOfWork(factory) as uow:
        rows = await uow.queries.list_by_user(current_user.id, limit=limit, offset=offset)
    return [
        QueryResponseSchema(
            id=str(q.id),
            input_text=q.input_text,
            intent=q.intent,
            response_text=q.response_text,
            model_used=q.model_used,
            tokens_used=q.tokens_used,
            cost_usd=q.cost_usd,
            latency_ms=q.latency_ms,
            source_message_ids=[str(m) for m in (q.source_message_ids or [])],
            created_at=q.created_at.isoformat() if q.created_at else "",
        )
        for q in rows
    ]

"""Schemas for query API."""

from pydantic import BaseModel, Field


class QueryCreateSchema(BaseModel):
    """POST /queries body."""

    input_text: str = Field(..., min_length=1, max_length=10000)


class QueryResponseSchema(BaseModel):
    """Query row for list/get (non-streaming)."""

    id: str
    input_text: str
    intent: str | None
    response_text: str | None
    model_used: str | None
    tokens_used: int | None
    cost_usd: float | None
    latency_ms: int | None
    source_message_ids: list[str] | None
    created_at: str

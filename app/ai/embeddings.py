"""
Embeddings for messages (and later people). OpenAI text-embedding-3-small, 1536 dimensions.
Logs usage to usage_events. Text is truncated before sending (see utils.text.truncate_for_embedding).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from app.config import get_settings
from app.utils.text import truncate_for_embedding

if TYPE_CHECKING:
    from app.repositories.usage_repository import UsageRepository

log = structlog.get_logger()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


async def embed_text(
    text: str,
    *,
    user_id: UUID,
    usage_repo: UsageRepository,
    event_type: str = "message_embedding",
    reference_id: UUID | None = None,
    reference_type: str | None = None,
    max_chars: int = 8000,
) -> list[float] | None:
    """
    Return 1536-dim embedding for text. Logs to usage_events. Returns None if API key missing or empty text.
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        log.warning("ai.embed_text.skip", reason="OPENAI_API_KEY not set")
        return None

    truncated = truncate_for_embedding(text or "", max_chars=max_chars)
    if not truncated.strip():
        return None

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        response = await client.embeddings.create(
            input=truncated,
            model=EMBEDDING_MODEL,
        )
    except Exception as e:
        log.exception("ai.embed_text.error", error=str(e))
        raise

    # Usage: response.usage has prompt_tokens, total_tokens
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", None) or 0

    await usage_repo.log_ai_call(
        user_id=user_id,
        event_type=event_type,
        model_used=EMBEDDING_MODEL,
        tokens_input=tokens,
        tokens_output=0,
        cost_usd=_embedding_cost_usd(tokens),
        reference_id=reference_id,
        reference_type=reference_type,
    )

    data = getattr(response, "data", []) or []
    if not data:
        return None
    return getattr(data[0], "embedding", None)


def _embedding_cost_usd(total_tokens: int) -> float:
    """Rough cost for text-embedding-3-small (~$0.02/1M tokens)."""
    return total_tokens / 1_000_000 * 0.02

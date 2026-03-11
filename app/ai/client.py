"""
Claude API wrapper. All AI calls go through call_claude(); auto-logs to usage_events table.
Uses Claude Haiku for high-frequency (extraction, sentiment, commitment); Sonnet for complex (Phase 6).
"""

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from app.config import get_settings

if TYPE_CHECKING:
    from app.repositories.usage_repository import UsageRepository

log = structlog.get_logger()

# Model names: Haiku for real-time/high-frequency, Sonnet for complex
MODEL_HAIKU = "claude-3-5-haiku-20241022"
MODEL_SONNET = "claude-3-5-sonnet-20241022"


def _sync_messages_create(**kwargs):  # noqa: ANN003
    """Sync Anthropic call; run in thread pool."""
    from anthropic import Anthropic
    client = Anthropic(api_key=kwargs.pop("_api_key"))
    return client.messages.create(**kwargs)


def _inject_system_cache(kwargs: dict) -> None:
    """If system is a string and use_system_cache is True, convert to cacheable block (persistent, 5 min)."""
    if not kwargs.get("use_system_cache") or "system" not in kwargs:
        return
    use_system_cache = kwargs.pop("use_system_cache", False)
    system = kwargs.get("system")
    if isinstance(system, str) and system and use_system_cache:
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "persistent", "ttl": 300}}
        ]
    elif use_system_cache:
        kwargs.pop("use_system_cache", None)


def _sync_stream(
    chunk_queue: queue.Queue,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    system: str | None,
    max_tokens: int,
    use_system_cache: bool = False,
) -> None:
    """Run sync stream; put text chunks in chunk_queue, then (None, usage_dict)."""
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if use_system_cache and system:
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "persistent", "ttl": 300}}
        ]
    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if text:
                    chunk_queue.put((text, None))
        msg = stream.get_final_message()
        usage = getattr(msg, "usage", None)
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", None) or 0,
            "output_tokens": getattr(usage, "output_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        }
        chunk_queue.put((None, usage_dict))
    except Exception as e:
        chunk_queue.put((None, {"error": e}))


async def call_claude(
    messages: list[dict[str, str]],
    *,
    model: str = MODEL_HAIKU,
    system: str | None = None,
    user_id: UUID,
    event_type: str,
    usage_repo: UsageRepository,
    reference_id: UUID | None = None,
    reference_type: str | None = None,
    max_tokens: int = 4096,
) -> str:
    """
    Call Anthropic Messages API; log usage to usage_events. Returns assistant text.
    """
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        log.warning("ai.call_claude.skip", reason="ANTHROPIC_API_KEY not set")
        return ""

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "_api_key": settings.ANTHROPIC_API_KEY,
    }
    if system:
        kwargs["system"] = system

    _inject_system_cache(kwargs)

    try:
        response = await asyncio.to_thread(_sync_messages_create, **kwargs)
    except Exception as e:
        log.exception("ai.call_claude.error", model=model, event_type=event_type, error=str(e))
        raise

    # Usage from response
    usage = getattr(response, "usage", None)
    tokens_input = getattr(usage, "input_tokens", None) or 0
    tokens_output = getattr(usage, "output_tokens", None) or 0
    tokens_cached = getattr(usage, "cache_creation_input_tokens", None) or 0

    # Log to usage_events
    await usage_repo.log_ai_call(
        user_id=user_id,
        event_type=event_type,
        model_used=model,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_cached=tokens_cached or None,
        cost_usd=estimate_cost_usd(model, tokens_input, tokens_output, tokens_cached),
        reference_id=reference_id,
        reference_type=reference_type,
    )

    # Extract text from content blocks
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    return "\n".join(text_parts).strip()


async def stream_claude(
    messages: list[dict[str, str]],
    *,
    model: str = MODEL_HAIKU,
    system: str | None = None,
    max_tokens: int = 4096,
    use_system_cache: bool = False,
    user_id: UUID | None = None,
    event_type: str = "query_stream",
    usage_repo: UsageRepository | None = None,
    reference_id: UUID | None = None,
    reference_type: str | None = None,
) -> AsyncGenerator[tuple[str | None, dict | None], None]:
    """
    Stream Claude response; yields (text_chunk, None) and finally (None, usage_dict).
    usage_dict has input_tokens, output_tokens, cache_creation_input_tokens (or "error" key).
    Optionally logs to usage_events when usage_repo and user_id are provided.
    """
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        log.warning("ai.stream_claude.skip", reason="ANTHROPIC_API_KEY not set")
        yield (None, {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0})
        return

    chunk_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    def run_stream() -> None:
        _sync_stream(
            chunk_queue,
            api_key=settings.ANTHROPIC_API_KEY,
            model=model,
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            use_system_cache=use_system_cache,
        )

    thread = loop.run_in_executor(None, run_stream)

    while True:
        item = await asyncio.to_thread(chunk_queue.get)
        text_part, usage_part = item
        if text_part is None:
            await thread  # ensure stream thread finished
            if usage_repo and user_id and "error" not in (usage_part or {}):
                u = usage_part or {}
                await usage_repo.log_ai_call(
                    user_id=user_id,
                    event_type=event_type,
                    model_used=model,
                    tokens_input=u.get("input_tokens", 0),
                    tokens_output=u.get("output_tokens", 0),
                    tokens_cached=u.get("cache_creation_input_tokens") or None,
                    cost_usd=estimate_cost_usd(
                        model,
                        u.get("input_tokens", 0),
                        u.get("output_tokens", 0),
                        u.get("cache_creation_input_tokens", 0),
                    ),
                    reference_id=reference_id,
                    reference_type=reference_type,
                )
            yield (None, usage_part)
            return
        yield (text_part, None)


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_tokens: int = 0
) -> float:
    """Rough USD cost estimate for logging. Update with current pricing if needed."""
    # Approximate per 1M tokens (as of 2024): Haiku input $0.80, output $4.00; Sonnet higher.
    if "haiku" in model.lower():
        input_per_m = 0.80
        output_per_m = 4.00
        cache_per_m = 0.30
    else:
        input_per_m = 3.00
        output_per_m = 15.00
        cache_per_m = 0.30
    input_billable = max(0, input_tokens - cache_tokens)
    return (
        input_billable / 1_000_000 * input_per_m
        + output_tokens / 1_000_000 * output_per_m
        + cache_tokens / 1_000_000 * cache_per_m
    )

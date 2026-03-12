"""
Slack connector: DM and group DM history via conversations.list + conversations.history.
User resolution via users.info with Redis cache. Routes all messages through ingest_message().
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.ingestion.base import BaseConnector, SyncResult, register_connector
from app.core.decorators import with_retry
from app.core.redis import get_redis_pool
from app.services.message_service import ingest_message
from app.utils.text import clean_message_body

log = structlog.get_logger()

SLACK_API_BASE = "https://slack.com/api"
# Tier 3 = 50+ req/min; use 1s base backoff for retries
SLACK_RATE_LIMIT_DELAY = 1.0


def _ts_to_datetime(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, TypeError):
        return None


@register_connector("slack")
class SlackConnector(BaseConnector):
    """Slack API connector. Uses bot token; DMs and group DMs only."""

    def get_source_type(self) -> str:
        return "slack"

    @with_retry(max_attempts=3, backoff_factor=1.0, exceptions=(httpx.HTTPStatusError,))
    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        url = f"{SLACK_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method,
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._access_token}"},
                **kwargs,
            )
            # Slack returns 200 with ok: false on auth/rate limit errors
            data = resp.json() if resp.content else {}
            if not data.get("ok"):
                raise httpx.HTTPStatusError(
                    f"Slack API error: {data.get('error', 'unknown')}",
                    request=resp.request,
                    response=resp,
                )
            return data

    async def validate_connection(self) -> bool:
        try:
            data = await self._request("GET", "/auth.test", params={})
            return bool(data.get("ok"))
        except Exception as e:
            log.warning("slack.validate_failed", error=str(e))
            return False

    async def refresh_token_if_needed(self) -> bool:
        # Slack bot tokens don't expire; just validate
        return await self.validate_connection()

    def _team_id(self) -> str:
        return (self.connection.slack_team_id or "unknown") if self.connection else "unknown"

    async def _resolve_user(self, user_id: str) -> str:
        """Resolve Slack user_id to display string. Cache in Redis TTL 3600s."""
        team_id = self._team_id()
        cache_key = f"slack_user:{team_id}:{user_id}"
        pool = get_redis_pool()
        client = None
        try:
            from redis.asyncio import Redis
            client = Redis(connection_pool=pool)
            cached = await client.get(cache_key)
            if cached:
                return cached
        finally:
            if client:
                await client.aclose()
        try:
            data = await self._request("GET", "/users.info", params={"user": user_id})
            user = (data.get("user") or {})
            display = user.get("real_name") or user.get("name") or user_id
            # Cache
            try:
                client2 = Redis(connection_pool=pool)
                await client2.setex(cache_key, 3600, display)
                await client2.aclose()
            except Exception:
                pass
            return display
        except Exception as e:
            log.warning("slack.users_info_failed", user_id=user_id, error=str(e))
            return user_id

    async def _list_conversations(self, types: str) -> list[dict]:
        """List conversations (im, mpim, or private channel). Cursor-paginated."""
        out: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"types": types, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = await self._request("GET", "/conversations.list", params=params)
            channels = data.get("channels") or []
            out.extend(channels)
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
            await asyncio.sleep(SLACK_RATE_LIMIT_DELAY)
        return out

    async def _fetch_history(
        self,
        channel_id: str,
        oldest: str | None = None,
        latest: str | None = None,
    ) -> list[dict]:
        """Fetch conversation history with cursor pagination."""
        messages: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if oldest:
                params["oldest"] = oldest
            if latest:
                params["latest"] = latest
            if cursor:
                params["cursor"] = cursor
            data = await self._request("GET", "/conversations.history", params=params)
            msgs = data.get("messages") or []
            messages.extend(msgs)
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
            await asyncio.sleep(SLACK_RATE_LIMIT_DELAY)
        return messages

    def _message_to_sender_and_body(self, msg: dict) -> tuple[str, str]:
        """Extract sender display and body text from a Slack message."""
        user_id = msg.get("user") or msg.get("bot_id") or "unknown"
        text = (msg.get("text") or "").strip()
        if not text and msg.get("files"):
            text = "[file attachment]"
        return user_id, clean_message_body(text)

    async def full_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["full_sync requires uow"])
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "slack"

        # List DMs and group DMs
        im_list = await self._list_conversations("im")
        mpim_list = await self._list_conversations("mpim")
        channels = im_list + mpim_list

        max_ts: float | None = None
        for ch in channels:
            ch_id = ch.get("id")
            if not ch_id:
                continue
            try:
                history = await self._fetch_history(ch_id)
            except Exception as e:
                result.errors.append(f"channel {ch_id}: {e}")
                continue
            for msg in history:
                if msg.get("subtype") == "bot_message" and not msg.get("text"):
                    continue
                ts = msg.get("ts")
                if not ts:
                    continue
                try:
                    ts_f = float(ts)
                    max_ts = ts_f if max_ts is None else max(max_ts, ts_f)
                except (ValueError, TypeError):
                    pass
                sent_at = _ts_to_datetime(ts) or datetime.now(timezone.utc)
                sender_id, body_clean = self._message_to_sender_and_body(msg)
                if isinstance(sender_id, str) and not sender_id.startswith("B"):
                    sender_display = await self._resolve_user(sender_id)
                else:
                    sender_display = sender_id
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=ts.replace(".", "_"),
                    thread_id=ch_id,
                    sender_raw=sender_display,
                    recipients_raw=None,
                    direction="inbound",
                    body_raw=body_clean,
                    message_type="slack",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
            await asyncio.sleep(SLACK_RATE_LIMIT_DELAY)

        if max_ts is not None:
            await uow.connections.update(self.connection, sync_cursor=str(max_ts))
        return result

    async def incremental_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["incremental_sync requires uow"])
        cursor = self.connection.sync_cursor
        if not cursor:
            return await self.full_sync(job_id, **kwargs)
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "slack"

        try:
            latest_ts_float = float(cursor)
        except (ValueError, TypeError):
            return await self.full_sync(job_id, **kwargs)

        im_list = await self._list_conversations("im")
        mpim_list = await self._list_conversations("mpim")
        channels = im_list + mpim_list
        now_ts = str(time.time())

        for ch in channels:
            ch_id = ch.get("id")
            if not ch_id:
                continue
            try:
                history = await self._fetch_history(ch_id, oldest=cursor, latest=now_ts)
            except Exception as e:
                result.errors.append(f"channel {ch_id}: {e}")
                continue
            for msg in history:
                if msg.get("subtype") == "bot_message" and not msg.get("text"):
                    continue
                ts = msg.get("ts")
                if not ts:
                    continue
                sent_at = _ts_to_datetime(ts) or datetime.now(timezone.utc)
                sender_id, body_clean = self._message_to_sender_and_body(msg)
                if isinstance(sender_id, str) and not sender_id.startswith("B"):
                    sender_display = await self._resolve_user(sender_id)
                else:
                    sender_display = sender_id
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=ts.replace(".", "_"),
                    thread_id=ch_id,
                    sender_raw=sender_display,
                    recipients_raw=None,
                    direction="inbound",
                    body_raw=body_clean,
                    message_type="slack",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
            await asyncio.sleep(SLACK_RATE_LIMIT_DELAY)

        await uow.connections.update(self.connection, sync_cursor=now_ts)
        return result

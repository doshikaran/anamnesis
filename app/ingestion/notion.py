"""
Notion connector: pages (search API) and database entries (query API). Top-level only.
OAuth tokens do not expire; no refresh logic. Rate limit 3 req/s.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.ingestion.base import BaseConnector, SyncResult, register_connector
from app.core.decorators import with_retry
from app.services.message_service import ingest_message

log = structlog.get_logger()

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_RATE_LIMIT_DELAY = 0.4  # ~2.5 req/s, under 3 req/s
PLAIN_TEXT_MAX_CHARS = 2000


def _extract_title(page: dict) -> str:
    """Notion pages store title in properties under key 'title' or 'Name'."""
    props = page.get("properties") or {}
    for key in ("title", "Name"):
        if key not in props:
            continue
        val = props[key]
        if not isinstance(val, dict):
            continue
        title_arr = val.get("title")
        if isinstance(title_arr, list) and len(title_arr) > 0:
            first = title_arr[0]
            if isinstance(first, dict) and "plain_text" in first:
                text = (first.get("plain_text") or "").strip()
                if text:
                    return text
    return "Untitled"


def _extract_plain_text(page: dict) -> str:
    """Extract plain_text from all rich_text property fields. Max 2000 chars."""
    parts: list[str] = []
    total = 0
    props = page.get("properties") or {}
    for _key, val in props.items():
        if not isinstance(val, dict) or val.get("type") != "rich_text":
            continue
        rich = val.get("rich_text")
        if not isinstance(rich, list):
            continue
        for item in rich:
            if not isinstance(item, dict):
                continue
            text = (item.get("plain_text") or "").strip()
            if not text:
                continue
            remaining = PLAIN_TEXT_MAX_CHARS - total
            if remaining <= 0:
                return "\n".join(parts)
            if len(text) > remaining:
                text = text[:remaining]
            parts.append(text)
            total += len(text)
            if total >= PLAIN_TEXT_MAX_CHARS:
                return "\n".join(parts)
    return "\n".join(parts)


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@register_connector("notion")
class NotionConnector(BaseConnector):
    """Notion API connector. OAuth tokens do not expire; no refresh needed."""

    def get_source_type(self) -> str:
        return "notion"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    @with_retry(max_attempts=3, backoff_factor=1.0, exceptions=(httpx.HTTPStatusError,))
    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{NOTION_API_BASE}{path}" if path.startswith("/") else f"{NOTION_API_BASE}/{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def validate_connection(self) -> bool:
        try:
            await self._request("GET", "/users/me")
            return True
        except Exception as e:
            log.warning("notion.validate_failed", error=str(e))
            return False

    async def refresh_token_if_needed(self) -> bool:
        # Notion OAuth tokens do not expire
        return False

    async def _search_pages(self, start_cursor: str | None = None) -> dict[str, Any]:
        """POST /v1/search with filter type=page. Paginate via start_cursor / has_more."""
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "sort": {"timestamp": "last_edited_time", "direction": "descending"},
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor
        return await self._request("POST", "/search", json=body)

    async def _search_databases(self, start_cursor: str | None = None) -> dict[str, Any]:
        """POST /v1/search with filter type=database. Paginate via start_cursor / has_more."""
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "database"},
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor
        return await self._request("POST", "/search", json=body)

    async def _query_database(
        self, database_id: str, start_cursor: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/databases/{id}/query. Paginate via start_cursor / has_more."""
        body: dict[str, Any] = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        return await self._request(
            "POST", f"/databases/{database_id}/query", json=body
        )

    async def full_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["full_sync requires uow"])
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "notion"
        cursor: str | None = None
        most_recent_edited: datetime | None = None

        while True:
            try:
                data = await self._search_pages(start_cursor=cursor)
            except Exception as e:
                result.errors.append(str(e))
                break
            pages = data.get("results") or []
            for page in pages:
                page_id = page.get("id")
                if not page_id:
                    continue
                last_edited = _parse_iso8601(page.get("last_edited_time"))
                if last_edited:
                    most_recent_edited = (
                        last_edited
                        if most_recent_edited is None
                        else max(most_recent_edited, last_edited)
                    )
                title = _extract_title(page)
                body_raw = _extract_plain_text(page)
                sent_at = last_edited or datetime.now(timezone.utc)
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=page_id,
                    thread_id=page_id,
                    sender_raw=None,
                    recipients_raw=None,
                    direction="internal",
                    subject=title or None,
                    body_raw=body_raw or None,
                    message_type="text",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
                await asyncio.sleep(NOTION_RATE_LIMIT_DELAY)
            cursor = data.get("next_cursor") if data.get("has_more") else None
            if not cursor:
                break

        # Database entries (query API)
        db_cursor: str | None = None
        while True:
            try:
                db_data = await self._search_databases(start_cursor=db_cursor)
            except Exception as e:
                result.errors.append(str(e))
                break
            databases = db_data.get("results") or []
            for db in databases:
                db_id = db.get("id")
                if not db_id:
                    continue
                await asyncio.sleep(NOTION_RATE_LIMIT_DELAY)
                row_cursor: str | None = None
                while True:
                    try:
                        row_data = await self._query_database(db_id, start_cursor=row_cursor)
                    except Exception as e:
                        result.errors.append(f"database {db_id}: {e}")
                        break
                    for page in row_data.get("results") or []:
                        page_id = page.get("id")
                        if not page_id:
                            continue
                        last_edited = _parse_iso8601(page.get("last_edited_time"))
                        if last_edited:
                            most_recent_edited = (
                                last_edited
                                if most_recent_edited is None
                                else max(most_recent_edited, last_edited)
                            )
                        title = _extract_title(page)
                        body_raw = _extract_plain_text(page)
                        sent_at = last_edited or datetime.now(timezone.utc)
                        msg_created = await ingest_message(
                            uow,
                            user_id,
                            connection_id,
                            source_type,
                            external_id=page_id,
                            thread_id=page_id,
                            sender_raw=None,
                            recipients_raw=None,
                            direction="internal",
                            subject=title or None,
                            body_raw=body_raw or None,
                            message_type="text",
                            sent_at=sent_at,
                        )
                        if msg_created is None:
                            result.skipped += 1
                        else:
                            result.created += 1
                        await asyncio.sleep(NOTION_RATE_LIMIT_DELAY)
                    row_cursor = row_data.get("next_cursor") if row_data.get("has_more") else None
                    if not row_cursor:
                        break
            db_cursor = db_data.get("next_cursor") if db_data.get("has_more") else None
            if not db_cursor:
                break

        if most_recent_edited is not None:
            await uow.connections.update(
                self.connection, sync_cursor=most_recent_edited.isoformat()
            )
        return result

    async def incremental_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["incremental_sync requires uow"])
        sync_cursor = self.connection.sync_cursor
        if not sync_cursor:
            return await self.full_sync(job_id, **kwargs)
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "notion"
        cursor: str | None = None
        most_recent_edited: datetime | None = None
        cursor_dt = _parse_iso8601(sync_cursor)
        if not cursor_dt:
            return await self.full_sync(job_id, **kwargs)

        while True:
            try:
                data = await self._search_pages(start_cursor=cursor)
            except Exception as e:
                result.errors.append(str(e))
                break
            pages = data.get("results") or []
            for page in pages:
                last_edited = _parse_iso8601(page.get("last_edited_time"))
                if last_edited is None or last_edited < cursor_dt:
                    continue
                page_id = page.get("id")
                if not page_id:
                    continue
                most_recent_edited = (
                    last_edited
                    if most_recent_edited is None
                    else max(most_recent_edited, last_edited)
                )
                title = _extract_title(page)
                body_raw = _extract_plain_text(page)
                sent_at = last_edited
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=page_id,
                    thread_id=page_id,
                    sender_raw=None,
                    recipients_raw=None,
                    direction="internal",
                    subject=title or None,
                    body_raw=body_raw or None,
                    message_type="text",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
                await asyncio.sleep(NOTION_RATE_LIMIT_DELAY)
            # If we got a page with last_edited < cursor_dt, we can stop (results sorted desc)
            last_in_batch = _parse_iso8601(pages[-1].get("last_edited_time")) if pages else None
            if last_in_batch is not None and last_in_batch < cursor_dt:
                break
            cursor = data.get("next_cursor") if data.get("has_more") else None
            if not cursor:
                break

        if most_recent_edited is not None:
            await uow.connections.update(
                self.connection, sync_cursor=most_recent_edited.isoformat()
            )
        return result

"""
Gmail connector: full_sync (1 year history), incremental_sync (historyId cursor),
token refresh, email cleaning, thread grouping. Uses httpx for async Gmail API.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.ingestion.base import BaseConnector, SyncResult, register_connector
from app.core.decorators import with_retry
from app.utils.text import clean_message_body
from app.services.message_service import ingest_message

log = structlog.get_logger()

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailConnector(BaseConnector):
    """Gmail API connector. Requires decrypted access_token and refresh_token."""

    def get_source_type(self) -> str:
        return "gmail"

    @with_retry(max_attempts=3, exceptions=(httpx.HTTPStatusError,))
    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{GMAIL_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def validate_connection(self) -> bool:
        try:
            await self._request("GET", "/profile")
            return True
        except Exception as e:
            log.warning("gmail.validate_failed", error=str(e))
            return False

    async def refresh_token_if_needed(self) -> bool:
        from app.config import get_settings
        settings = get_settings()
        expires_at = self.connection.token_expires_at
        if not expires_at or not self._refresh_token:
            return False
        # Refresh if expiring within 5 minutes
        threshold = datetime.now(timezone.utc) + timedelta(minutes=5)
        if expires_at.tzinfo is None:
            threshold = threshold.replace(tzinfo=timezone.utc)
        if expires_at <= threshold:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                r.raise_for_status()
                data = r.json()
            self._access_token = data["access_token"]
            # Caller must persist new token; we don't have DB here
            return True
        return False

    def _parse_rfc2822(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value)
        except Exception:
            return None

    def _extract_payload(self, msg: dict) -> tuple[str, str, str, list[str], datetime | None]:
        """Extract subject, body (plain), from, to (recipients), date from Gmail message payload."""
        headers: dict[str, str] = {}
        for h in msg.get("payload", {}).get("headers", []):
            name = (h.get("name") or "").lower()
            if name:
                headers[name] = h.get("value") or ""
        subject = headers.get("subject", "")
        from_val = headers.get("from", "")
        to_val = headers.get("to", "")
        date_str = headers.get("date")
        sent_at = self._parse_rfc2822(date_str)
        body = ""
        payload = msg.get("payload", {})
        if payload.get("body", {}).get("data"):
            import base64
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        else:
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    import base64
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    break
        body_clean = clean_message_body(body)
        recipients_raw = [s.strip() for s in to_val.split(",") if s.strip()] if to_val else []
        return subject, body_clean, from_val, recipients_raw, sent_at

    async def full_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["full_sync requires uow"])
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "gmail"
        # Sync last 1 year
        after = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y/%m/%d")
        q = f"after:{after}"
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"maxResults": 100, "q": q}
            if page_token:
                params["pageToken"] = page_token
            try:
                data = await self._request("GET", "/messages", params=params)
            except Exception as e:
                result.errors.append(str(e))
                break
            messages = data.get("messages") or []
            for m in messages:
                msg_id = m.get("id")
                if not msg_id:
                    continue
                try:
                    full_msg = await self._request("GET", f"/messages/{msg_id}?format=full")
                except Exception as e:
                    result.errors.append(f"message {msg_id}: {e}")
                    continue
                subject, body_clean, from_val, recipients_raw, sent_at = self._extract_payload(full_msg)
                if not sent_at:
                    sent_at = datetime.now(timezone.utc)
                thread_id_ext = full_msg.get("threadId") or None
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=msg_id,
                    thread_id=thread_id_ext,
                    sender_raw=from_val or None,
                    recipients_raw=recipients_raw or None,
                    direction="inbound",
                    subject=subject or None,
                    body_raw=body_clean,
                    message_type="email",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        # Set historyId for future incremental sync
        try:
            profile = await self._request("GET", "/profile")
            if profile.get("historyId"):
                await uow.connections.update(self.connection, sync_cursor=str(profile["historyId"]))
        except Exception:
            pass
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
        source_type = "gmail"
        try:
            data = await self._request("GET", f"/history?startHistoryId={cursor}&historyTypes=message&maxResults=100")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # historyId no longer valid, fall back to full
                return await self.full_sync(job_id, **kwargs)
            result.errors.append(str(e))
            return result
        for entry in data.get("history", []):
            for msg_meta in entry.get("messagesAdded", []):
                msg = msg_meta.get("message")
                if not msg:
                    continue
                msg_id = msg.get("id")
                if not msg_id:
                    continue
                try:
                    full_msg = await self._request("GET", f"/messages/{msg_id}?format=full")
                except Exception as e:
                    result.errors.append(f"message {msg_id}: {e}")
                    continue
                subject, body_clean, from_val, recipients_raw, sent_at = self._extract_payload(full_msg)
                if not sent_at:
                    sent_at = datetime.now(timezone.utc)
                thread_id_ext = full_msg.get("threadId") or None
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=msg_id,
                    thread_id=thread_id_ext,
                    sender_raw=from_val or None,
                    recipients_raw=recipients_raw or None,
                    direction="inbound",
                    subject=subject or None,
                    body_raw=body_clean,
                    message_type="email",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
        # Update historyId for next incremental (from profile or last response)
        new_history = data.get("historyId")
        if new_history:
            await uow.connections.update(self.connection, sync_cursor=str(new_history))
        return result


register_connector("gmail")(GmailConnector)

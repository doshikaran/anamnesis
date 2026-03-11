"""
Google Calendar connector: events, attendees, recurring detection.
Stores each event as a message (message_type='text') for Phase 3; external_id = event id.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.ingestion.base import BaseConnector, SyncResult, register_connector
from app.core.decorators import with_retry
from app.services.message_service import ingest_message

log = structlog.get_logger()

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"


class GoogleCalendarConnector(BaseConnector):
    """Google Calendar API connector. Uses same OAuth token pattern as Gmail."""

    def get_source_type(self) -> str:
        return "google_calendar"

    @with_retry(max_attempts=3, exceptions=(httpx.HTTPStatusError,))
    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{CALENDAR_API_BASE}{path}"
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
            await self._request("GET", "/events?maxResults=1")
            return True
        except Exception as e:
            log.warning("google_calendar.validate_failed", error=str(e))
            return False

    async def refresh_token_if_needed(self) -> bool:
        from app.config import get_settings
        settings = get_settings()
        expires_at = self.connection.token_expires_at
        if not expires_at or not self._refresh_token:
            return False
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
            return True
        return False

    def _parse_rfc3339(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def _event_to_body(self, event: dict) -> str:
        """Build body_clean from event summary, description, attendees."""
        parts = []
        if event.get("summary"):
            parts.append(event["summary"])
        if event.get("description"):
            parts.append(event["description"])
        attendees = event.get("attendees") or []
        if attendees:
            names = [a.get("displayName") or a.get("email") for a in attendees if a.get("displayName") or a.get("email")]
            if names:
                parts.append("Attendees: " + ", ".join(names[:10]))
        if event.get("recurrence"):
            parts.append("[Recurring]")
        return "\n".join(parts).strip() or "Calendar event"

    async def full_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["full_sync requires uow"])
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "google_calendar"
        time_min = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat().replace("+00:00", "Z")
        time_max = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat().replace("+00:00", "Z")
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "maxResults": 250,
                "singleEvents": True,
                "timeMin": time_min,
                "timeMax": time_max,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                data = await self._request("GET", "/events", params=params)
            except Exception as e:
                result.errors.append(str(e))
                break
            for event in data.get("items") or []:
                event_id = event.get("id")
                if not event_id or event.get("status") == "cancelled":
                    continue
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                sent_at = self._parse_rfc3339(start) or datetime.now(timezone.utc)
                body_clean = self._event_to_body(event)
                subject = event.get("summary") or "Calendar event"
                sender_raw = event.get("organizer", {}).get("email") if event.get("organizer") else None
                msg_created = await ingest_message(
                    uow,
                    user_id,
                    connection_id,
                    source_type,
                    external_id=event_id,
                    thread_id=event_id,
                    sender_raw=sender_raw,
                    direction="internal",
                    subject=subject,
                    body_raw=body_clean,
                    message_type="text",
                    sent_at=sent_at,
                )
                if msg_created is None:
                    result.skipped += 1
                else:
                    result.created += 1
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return result

    async def incremental_sync(self, job_id: UUID, **kwargs: object) -> SyncResult:
        sync_token = self.connection.sync_cursor
        if not sync_token:
            return await self.full_sync(job_id, **kwargs)
        uow = kwargs.get("uow")
        if not uow:
            return SyncResult(errors=["incremental_sync requires uow"])
        result = SyncResult()
        user_id = self.connection.user_id
        connection_id = self.connection.id
        source_type = "google_calendar"
        try:
            data = await self._request("GET", "/events", params={"syncToken": sync_token})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 410:
                return await self.full_sync(job_id, **kwargs)
            result.errors.append(str(e))
            return result
        for event in data.get("items") or []:
            event_id = event.get("id")
            if not event_id:
                continue
            if event.get("status") == "cancelled":
                result.skipped += 1
                continue
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            sent_at = self._parse_rfc3339(start) or datetime.now(timezone.utc)
            body_clean = self._event_to_body(event)
            subject = event.get("summary") or "Calendar event"
            sender_raw = event.get("organizer", {}).get("email") if event.get("organizer") else None
            msg_created = await ingest_message(
                uow,
                user_id,
                connection_id,
                source_type,
                external_id=event_id,
                thread_id=event_id,
                sender_raw=sender_raw,
                direction="internal",
                subject=subject,
                body_raw=body_clean,
                message_type="text",
                sent_at=sent_at,
            )
            if msg_created is None:
                result.skipped += 1
            else:
                result.created += 1
        if data.get("nextSyncToken"):
            await uow.connections.update(self.connection, sync_cursor=data["nextSyncToken"])
        return result


register_connector("google_calendar")(GoogleCalendarConnector)

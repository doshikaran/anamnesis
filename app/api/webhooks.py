"""
Webhooks API: receive callbacks from Slack, Microsoft Graph, etc. Phase 8.
Validation/challenge endpoints return immediately; event payloads are acknowledged and processed async (stub).
"""

import hashlib
import hmac
import structlog
from fastapi import APIRouter, Request, Header, Response
from fastapi.responses import PlainTextResponse

from app.config import get_settings

router = APIRouter()
log = structlog.get_logger()


# ---------- Slack Events API ----------
@router.post("/slack")
async def webhook_slack(
    request: Request,
    x_slack_signature: str | None = Header(None, alias="X-Slack-Signature"),
):
    """
    Slack Events API endpoint. Verifies signature; responds to url_verification challenge;
    otherwise returns 200 and queues event processing (Phase 8 stub).
    """
    settings = get_settings()
    body = await request.body()
    if not settings.SLACK_SIGNING_SECRET:
        log.warning("webhooks.slack.skip", reason="SLACK_SIGNING_SECRET not set")
        return Response(status_code=200)

    if x_slack_signature:
        sig_baseline = hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        expected = f"v0={sig_baseline}"
        if not hmac.compare_digest(x_slack_signature, expected):
            log.warning("webhooks.slack.invalid_signature")
            return Response(status_code=401)

    try:
        import json
        payload = json.loads(body.decode()) if body else {}
    except Exception:
        payload = {}

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # Event received — acknowledge and process async (Phase 8: no worker yet)
    event = payload.get("event", {})
    log.info(
        "webhooks.slack.event",
        type=event.get("type"),
        channel=event.get("channel"),
    )
    return Response(status_code=200)


# ---------- Microsoft Graph subscriptions ----------
@router.get("/microsoft")
async def webhook_microsoft_validate(
    validation_token: str | None = None,
):
    """
    Microsoft Graph subscription validation. GET with validationToken query param;
    return the token as plain text and 200.
    """
    if validation_token:
        return PlainTextResponse(content=validation_token)
    return Response(status_code=400)


@router.post("/microsoft")
async def webhook_microsoft_notify(request: Request):
    """
    Microsoft Graph subscription notifications. Acknowledge with 202;
    process lifecycle and resource data in background (Phase 8 stub).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    notifications = body.get("value", [])
    for n in notifications:
        log.info(
            "webhooks.microsoft.notification",
            subscription_id=n.get("subscriptionId"),
            change_type=n.get("changeType"),
            resource=n.get("resource"),
        )
    return Response(status_code=202)


# ---------- Outlook / Teams / Calendar (same Microsoft Graph pattern; optional separate paths) ----------
@router.get("/outlook")
async def webhook_outlook_validate(validation_token: str | None = None):
    """Outlook subscription validation. Phase 8 stub."""
    if validation_token:
        return PlainTextResponse(content=validation_token)
    return Response(status_code=400)


@router.post("/outlook")
async def webhook_outlook_notify(request: Request):
    """Outlook mail/calendar notifications. Phase 8 stub."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    log.info("webhooks.outlook.notify", value_count=len(body.get("value", [])))
    return Response(status_code=202)


@router.get("/teams")
async def webhook_teams_validate(validation_token: str | None = None):
    """Teams subscription validation. Phase 8 stub."""
    if validation_token:
        return PlainTextResponse(content=validation_token)
    return Response(status_code=400)


@router.post("/teams")
async def webhook_teams_notify(request: Request):
    """Teams chat/meeting notifications. Phase 8 stub."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    log.info("webhooks.teams.notify", value_count=len(body.get("value", [])))
    return Response(status_code=202)


@router.get("/notion")
async def webhook_notion_validate(request: Request):
    """Notion integration verification. Phase 8 stub."""
    return Response(status_code=200)


@router.post("/notion")
async def webhook_notion_notify(request: Request):
    """Notion page/database updates. Phase 8 stub."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    log.info("webhooks.notion.notify", keys=list(body.keys()) if isinstance(body, dict) else [])
    return Response(status_code=200)

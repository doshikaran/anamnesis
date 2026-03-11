"""
Phase 7: Web Push delivery. Sends push notifications via VAPID to user's push subscription.
"""

from typing import Any

import structlog

from app.config import get_settings

log = structlog.get_logger()


def send_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    action_url: str | None = None,
) -> tuple[bool, str | None]:
    """
    Send a Web Push notification. Uses pywebpush with VAPID.
    Returns (success: bool, error_message: str | None).
    """
    settings = get_settings()
    if not settings.VAPID_PRIVATE_KEY:
        log.warning("push.skip", reason="VAPID_PRIVATE_KEY not set")
        return False, "Push not configured"

    if not endpoint or not p256dh or not auth:
        return False, "Missing subscription keys"

    try:
        import pywebpush
        subscription_info = {
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        }
        payload: dict[str, Any] = {
            "title": title[:200],
            "body": body[:500],
        }
        if action_url:
            payload["url"] = action_url[:500]

        import json as _json
        data = _json.dumps(payload).encode("utf-8")

        pywebpush.webpush(
            subscription_info,
            data,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_EMAIL} if settings.VAPID_EMAIL else None,
        )
        log.info("push.sent", endpoint_prefix=endpoint[:50])
        return True, None
    except Exception as e:
        err_msg = str(e)
        log.warning("push.failed", error=err_msg, endpoint_prefix=endpoint[:50])
        return False, err_msg

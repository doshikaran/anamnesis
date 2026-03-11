"""
Timezone handling, deadline inference from text, user timezone conversion.
"""

from datetime import date, datetime, time, timedelta, timezone
import re

# Default for "no timezone" is UTC
UTC = timezone.utc


def utcnow() -> datetime:
    """Current time in UTC (timezone-aware)."""
    return datetime.now(UTC)


def to_user_timezone(dt: datetime | None, user_tz: str = "UTC") -> datetime | None:
    """
    Convert UTC datetime to user's timezone.
    user_tz: IANA name e.g. 'America/New_York'. Falls back to UTC if invalid.
    """
    if dt is None:
        return None
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(user_tz)
        return dt.astimezone(tz)
    except Exception:
        return dt.astimezone(UTC)


def parse_deadline_from_text(text: str | None) -> tuple[datetime | None, str, float]:
    """
    Parse explicit date/time mentions from text.
    Returns (datetime or None, raw_string_found, confidence 0..1).
    """
    if not text or not text.strip():
        return None, "", 0.0
    text_lower = text.strip().lower()
    # Simple patterns: "by Friday", "due 3/15", "by end of day", "tomorrow"
    # Minimal implementation for Phase 3; can be extended with dateparser later.
    today = date.today()
    if "tomorrow" in text_lower:
        d = today + timedelta(days=1)
        return datetime.combine(d, datetime.min.time()).replace(tzinfo=UTC), "tomorrow", 0.9
    if "end of day" in text_lower or "eod" in text_lower:
        d = today
        return datetime.combine(d, time(23, 59, 59), tzinfo=UTC), "end of day", 0.85
    if "next week" in text_lower:
        # Next Monday
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        d = today + timedelta(days=days_ahead)
        return datetime.combine(d, datetime.min.time()).replace(tzinfo=UTC), "next week", 0.8
    # US style MM/DD or MM/DD/YY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if year:
            y = int(year) if len(year) == 4 else 2000 + int(year)
        else:
            y = today.year
        try:
            d = date(y, month, day)
            if d < today:
                d = d.replace(year=today.year + 1)
            return datetime.combine(d, datetime.min.time()).replace(tzinfo=UTC), m.group(0), 0.9
        except ValueError:
            pass
    return None, "", 0.0


def infer_deadline_datetime(
    raw: str | None,
    fallback_days: int | None = 7,
) -> tuple[datetime | None, str, float]:
    """
    Infer deadline from raw text. Uses parse_deadline_from_text; if nothing found
    and fallback_days set, return (now + fallback_days, 'inferred', confidence).
    """
    dt, raw_str, conf = parse_deadline_from_text(raw)
    if dt is not None:
        return dt, raw_str, conf
    if fallback_days is not None and fallback_days > 0:
        d = date.today() + timedelta(days=fallback_days)
        return datetime.combine(d, datetime.min.time()).replace(tzinfo=UTC), "inferred", 0.3
    return None, "", 0.0

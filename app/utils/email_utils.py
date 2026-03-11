"""
Email parsing: parse From/To headers, extract name and email, detect automated senders.
"""

import re
from dataclasses import dataclass

# Patterns for "Name <email>" or "email" or "<email>"
NAME_EMAIL_RE = re.compile(
    r"^(?:(.+?)\s*<([^>]+)>|<([^>]+)>|([^\s<]+@[^\s>]+))$",
    re.IGNORECASE,
)
# Just email
EMAIL_ONLY_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


@dataclass
class ParsedEmail:
    """Parsed sender or recipient."""

    name: str | None
    email: str


def parse_email_address(header_value: str | None) -> ParsedEmail | None:
    """
    Parse a single From/To header value.
    Examples: "John <john@example.com>", "john@example.com", "<john@example.com>"
    """
    if not header_value or not header_value.strip():
        return None
    value = header_value.strip()
    match = NAME_EMAIL_RE.match(value)
    if match:
        g = match.groups()
        if g[0] and g[1]:  # "Name <email>"
            return ParsedEmail(name=g[0].strip().strip('"'), email=g[1].strip().lower())
        if g[2]:  # "<email>"
            return ParsedEmail(name=None, email=g[2].strip().lower())
        if g[3]:  # bare email
            return ParsedEmail(name=None, email=g[3].strip().lower())
    # Fallback: extract first email
    emails = EMAIL_ONLY_RE.findall(value)
    if emails:
        return ParsedEmail(name=None, email=emails[0].lower())
    return None


def extract_name_from_email(email: str) -> str:
    """Derive a display name from email local part (e.g. john.doe -> John Doe)."""
    if not email or "@" not in email:
        return email or "Unknown"
    local = email.split("@")[0]
    # Replace dots/underscores with space and title-case
    name = re.sub(r"[._-]+", " ", local).strip()
    return name.title() if name else local


# Common automated / no-reply senders (subset)
AUTOMATED_DOMAINS = (
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "notifications",
    "notification",
    "alert",
    "automated",
    "support@",
    "info@",
)
AUTOMATED_LOCAL_PARTS = ("noreply", "no-reply", "donotreply", "notifications", "alerts")


def is_automated_sender(email: str | None, name: str | None = None) -> bool:
    """Heuristic: treat common no-reply and notification addresses as automated."""
    if not email:
        return True
    email_lower = email.lower()
    local = email_lower.split("@")[0] if "@" in email_lower else ""
    if local in AUTOMATED_LOCAL_PARTS:
        return True
    for prefix in AUTOMATED_DOMAINS:
        if prefix in email_lower:
            return True
    return False


def normalize_email(email: str | None) -> str | None:
    """Lowercase and strip. Return None if empty."""
    if not email or not email.strip():
        return None
    return email.strip().lower()

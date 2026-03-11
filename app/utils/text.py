"""
Text cleaning: strip email signatures, strip HTML, clean message body, truncate for embedding.
"""

import re
from html import unescape

# Common signature delimiters
SIGNATURE_PATTERNS = [
    r"\n--\s*\n",  # "-- " on its own line
    r"\n_{3,}\s*\n",  # underscores
    r"\n-{3,}\s*\n",  # dashes
    r"\nSent from my (iPhone|Android|Galaxy|iPad)",  # mobile
    r"\nGet Outlook for",  # Outlook
    r"\nOn .+ wrote:\s*$",  # "On ... wrote:"
    r"\n-{2,}\s*Original Message\s*-{2,}",  # Original Message
    r"\nFrom:.*\nSent:.*\nTo:.*\nSubject:.*\n",  # Forward header block
]

# Compiled once
SIG_RE = re.compile("|".join(f"({p})" for p in SIGNATURE_PATTERNS), re.IGNORECASE)

# HTML tag strip
HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    """Remove HTML tags. Unescape entities."""
    if not text or not text.strip():
        return ""
    cleaned = HTML_TAG_RE.sub(" ", text)
    return unescape(cleaned).strip()


def strip_email_signature(body: str | None) -> str:
    """
    Remove common email signature and quoted-reply blocks from the end of body.
    Keeps the first (newest) part of the message.
    """
    if not body or not body.strip():
        return ""
    # Split by first occurrence of any signature pattern; keep the first part
    parts = SIG_RE.split(body, maxsplit=1)
    first = (parts[0] if parts else body).strip()
    return first


def clean_message_body(raw: str | None) -> str:
    """
    Full clean: strip HTML, then strip signature, normalize whitespace.
    Used for body_clean before storage and for embedding.
    """
    if not raw:
        return ""
    no_html = strip_html(raw)
    no_sig = strip_email_signature(no_html)
    # Normalize whitespace
    normalized = " ".join(no_sig.split())
    return normalized.strip()


def truncate_for_embedding(text: str, max_chars: int = 8000) -> str:
    """
    Truncate text to max_chars for embedding API (e.g. 8k chars ~ 2k tokens).
    Avoids cutting mid-word if possible.
    """
    if not text or len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space].strip()
    return truncated.strip()

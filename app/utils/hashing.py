"""
Content hashing for deduplication. SHA-256 of normalized body.
"""

import hashlib
import unicodedata


def normalize_for_hash(text: str | None) -> str:
    """
    Normalize text before hashing: lowercase, NFKC, collapse whitespace.
    Ensures same content produces same hash across encodings.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = " ".join(normalized.lower().split())
    return normalized.strip()


def content_hash(body: str | None) -> str | None:
    """
    SHA-256 hash of normalized body. Used for message deduplication.
    Returns None if body is empty.
    """
    normalized = normalize_for_hash(body)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

"""
Custom exception classes. All API errors flow through these.
Global exception handler in main.py formats them consistently.
"""

from typing import Any


class AnamnesisException(Exception):
    """Base exception for all Anamnesis errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AnamnesisException):
    """Resource not found. Use 404 — do not reveal existence of other users' data."""

    def __init__(self, code: str = "NOT_FOUND", message: str = "Resource not found"):
        super().__init__(code=code, message=message, status_code=404)


class UnauthorizedError(AnamnesisException):
    """Authentication required or invalid token."""

    def __init__(self, code: str = "UNAUTHORIZED", message: str = "Invalid or expired token"):
        super().__init__(code=code, message=message, status_code=401)


class ForbiddenError(AnamnesisException):
    """Authenticated but not allowed to perform this action."""

    def __init__(self, code: str = "FORBIDDEN", message: str = "Not allowed"):
        super().__init__(code=code, message=message, status_code=403)


class ValidationError(AnamnesisException):
    """Invalid input (422)."""

    def __init__(self, code: str = "VALIDATION_ERROR", message: str = "Invalid input", details: dict[str, Any] | None = None):
        super().__init__(code=code, message=message, status_code=422, details=details or {})


class RateLimitError(AnamnesisException):
    """Too many requests (429)."""

    def __init__(
        self,
        code: str = "RATE_LIMIT_EXCEEDED",
        message: str = "Too many requests",
        retry_after: int | None = None,
    ):
        details: dict[str, Any] = {}
        if retry_after is not None:
            details["retry_after"] = retry_after
        super().__init__(code=code, message=message, status_code=429, details=details)
        self.retry_after = retry_after


class ExternalAPIError(AnamnesisException):
    """OAuth provider or external API failure (502)."""

    def __init__(self, code: str = "EXTERNAL_API_ERROR", message: str = "External service error"):
        super().__init__(code=code, message=message, status_code=502)

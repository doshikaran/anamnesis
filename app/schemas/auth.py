"""Auth request/response schemas."""

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 min in seconds


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    avatar_url: str | None
    auth_provider: str
    timezone: str
    onboarding_complete: bool
    plan: str

    class Config:
        from_attributes = True


class OAuthStateSchema(BaseModel):
    """State param for OAuth flow (e.g. base64 JSON)."""
    provider: str  # 'google' | 'microsoft'
    redirect_uri: str | None = None
    connection_source_type: str | None = None  # e.g. 'gmail', 'outlook_mail'


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Current refresh token")

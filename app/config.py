"""
Configuration management. All config in one place.
Secrets from AWS Secrets Manager in production; .env in development.
Never use os.getenv() in business code — always use settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every env var is typed, documented, and has a sensible default or is required."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # App
    APP_ENV: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Environment; production loads secrets from AWS Secrets Manager",
    )
    SECRET_KEY: str = Field(default="", description="JWT signing key")
    VAPID_PRIVATE_KEY: str = Field(default="", description="Web Push VAPID private key")
    VAPID_EMAIL: str = Field(default="mailto:admin@example.com", description="Web Push contact email")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://anamnesis:anamnesis_dev@localhost:5432/anamnesis",
        description="Async PostgreSQL URL",
    )
    DATABASE_POOL_SIZE: int = Field(default=20, ge=1, le=100)
    DATABASE_MAX_OVERFLOW: int = Field(default=10, ge=0, le=50)

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis URL for Celery and cache")

    # AWS
    AWS_REGION: str = Field(default="us-east-1")
    AWS_ACCESS_KEY_ID: str = Field(default="")
    AWS_SECRET_ACCESS_KEY: str = Field(default="")
    S3_BUCKET_NAME: str = Field(default="anamnesis-uploads")
    AWS_SECRETS_MANAGER_PREFIX: str = Field(default="anamnesis/", description="Prefix for secret names")

    # Google OAuth
    GOOGLE_CLIENT_ID: str = Field(default="")
    GOOGLE_CLIENT_SECRET: str = Field(default="")
    GOOGLE_REDIRECT_URI: str = Field(default="http://localhost:3000/auth/google/callback")

    # Microsoft OAuth
    MICROSOFT_CLIENT_ID: str = Field(default="")
    MICROSOFT_CLIENT_SECRET: str = Field(default="")
    MICROSOFT_TENANT_ID: str = Field(default="common")
    MICROSOFT_REDIRECT_URI: str = Field(default="http://localhost:3000/auth/microsoft/callback")

    # Slack OAuth
    SLACK_CLIENT_ID: str = Field(default="")
    SLACK_CLIENT_SECRET: str = Field(default="")
    SLACK_REDIRECT_URI: str = Field(default="http://localhost:3000/auth/slack/callback")
    SLACK_SIGNING_SECRET: str = Field(default="")

    # Notion OAuth
    NOTION_CLIENT_ID: str = Field(default="")
    NOTION_CLIENT_SECRET: str = Field(default="")
    NOTION_REDIRECT_URI: str = Field(default="http://localhost:3000/auth/notion/callback")

    # AI
    ANTHROPIC_API_KEY: str = Field(default="")
    OPENAI_API_KEY: str = Field(default="")

    # Encryption
    ENCRYPTION_MASTER_KEY: str = Field(default="", description="Fernet key for token encryption")

    # Frontend
    FRONTEND_URL: str = Field(default="http://localhost:3000", description="CORS and OAuth redirect whitelist")

    # Optional
    SENTRY_DSN: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


def _inject_aws_secrets_into_env() -> None:
    """In production, load from AWS Secrets Manager and set env vars (for Settings to read)."""
    import os
    if os.getenv("APP_ENV") != "production":
        return
    try:
        import boto3
        import json
        region = os.getenv("AWS_REGION", "us-east-1")
        prefix = (os.getenv("AWS_SECRETS_MANAGER_PREFIX") or "anamnesis/").rstrip("/")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=f"{prefix}/app")
        secrets = json.loads(response.get("SecretString", "{}"))
        for k, v in secrets.items():
            if v and isinstance(k, str) and k.isupper():
                os.environ.setdefault(k, str(v))
    except Exception:
        pass


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. In production, overlays AWS Secrets Manager onto env."""
    _inject_aws_secrets_into_env()
    return Settings()


settings = get_settings()

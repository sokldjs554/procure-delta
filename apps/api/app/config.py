from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ProcureDelta API"
    database_url: str = (
        "postgresql+psycopg://procure_delta:procure_delta@postgres:5432/procure_delta"
    )
    redis_url: str = "redis://redis:6379/0"
    attachment_storage_path: Path = Path("/var/lib/procure-delta")
    attachment_max_bytes: int = 10 * 1024 * 1024
    koneps_enabled: bool = False
    koneps_service_key: SecretStr | None = None
    koneps_lookback_days: int = Field(default=1, ge=1, le=30)
    extraction_mode: Literal["deterministic", "hosted"] = "deterministic"
    extraction_endpoint: str | None = None
    extraction_provider: str | None = None
    extraction_model: str | None = None
    extraction_api_key: SecretStr | None = None
    extraction_max_completion_tokens: int = Field(default=4096, ge=1, le=32768)
    notification_external_enabled: bool = False
    notification_webhook_destinations: dict[str, SecretStr] = Field(default_factory=dict)
    demo_auth_enabled: bool = True
    demo_operator_secret: SecretStr | None = None
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86400, ge=300, le=86400)
    cors_origins: list[str] = ["http://localhost:3000"]
    release_revision: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

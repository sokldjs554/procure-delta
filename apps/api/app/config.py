from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ProcureDelta API"
    database_url: str = (
        "postgresql+psycopg://procure_delta:procure_delta@postgres:5432/procure_delta"
    )
    redis_url: str = "redis://redis:6379/0"
    attachment_storage_path: Path = Path("/var/lib/procure-delta")
    attachment_storage_backend: Literal["local", "s3"] = "local"
    attachment_s3_bucket: str | None = None
    attachment_s3_prefix: str = "procure-delta"
    attachment_s3_region: str | None = None
    attachment_s3_endpoint_url: str | None = None
    attachment_s3_access_key_id: SecretStr | None = None
    attachment_s3_secret_access_key: SecretStr | None = None
    attachment_max_bytes: int = 10 * 1024 * 1024
    ocr_backend: Literal["fixture", "tesseract"] = "fixture"
    ocr_tessdata_dir: Path = Path("/usr/share/tesseract-ocr/5/tessdata")
    ocr_language: Literal["kor+eng", "kor", "eng"] = "kor+eng"
    ocr_dpi: int = Field(default=300, ge=72, le=300)
    ocr_max_pages: int = Field(default=10, ge=1, le=30)
    ocr_max_pixels_per_page: int = Field(default=12_000_000, ge=1, le=20_000_000)
    ocr_timeout_seconds: float = Field(default=40, ge=1, le=45)
    koneps_enabled: bool = False
    koneps_service_key: SecretStr | None = None
    koneps_lookback_days: int = Field(default=1, ge=1, le=30)
    koneps_pages_per_poll: int = Field(default=5, ge=1, le=100)
    normalization_batch_size: int = Field(default=100, ge=1, le=1000)
    extraction_mode: Literal["deterministic", "hosted"] = "deterministic"
    extraction_endpoint: str | None = None
    extraction_provider: str | None = None
    extraction_model: str | None = None
    extraction_api_key: SecretStr | None = None
    extraction_max_completion_tokens: int = Field(default=4096, ge=1, le=32768)
    extraction_credits_enabled: bool = False
    extraction_credit_account: str | None = Field(default=None, max_length=255)
    extraction_credit_units: int = Field(default=1, ge=1, le=1_000_000)
    notification_external_enabled: bool = False
    notification_webhook_destinations: dict[str, SecretStr] = Field(default_factory=dict)
    notification_webhook_formats: dict[str, Literal["generic", "slack"]] = Field(
        default_factory=dict
    )
    notification_smtp_host: str | None = None
    notification_smtp_port: int = Field(default=587, ge=1, le=65535)
    notification_smtp_starttls: bool = True
    notification_smtp_username: SecretStr | None = None
    notification_smtp_password: SecretStr | None = None
    notification_email_sender: str | None = None
    notification_email_recipients: dict[str, SecretStr] = Field(default_factory=dict)
    demo_auth_enabled: bool = True
    demo_operator_secret: SecretStr | None = None
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86400, ge=300, le=86400)
    cors_origins: list[str] = ["http://localhost:3000"]
    release_revision: str = Field(
        default="development",
        validation_alias=AliasChoices("release_revision", "RENDER_GIT_COMMIT"),
    )
    sentry_enabled: bool = False
    sentry_dsn: SecretStr | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("extraction_credit_units", mode="before")
    @classmethod
    def whole_credit_units(cls, value: object) -> int:
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        if type(value) is not int:
            raise ValueError("extraction credit units must be a whole integer")
        return value

    @field_validator("extraction_credit_account")
    @classmethod
    def normalize_credit_account(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_credit_policy(self) -> Self:
        if self.extraction_credits_enabled and (
            self.extraction_mode != "hosted" or not self.extraction_credit_account
        ):
            raise ValueError("extraction credits require hosted mode and an explicit account")
        return self

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_driver(cls, value: object) -> object:
        return normalize_database_url(value) if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def accept_single_cors_origin(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("attachment_s3_prefix")
    @classmethod
    def safe_storage_prefix(cls, value: str) -> str:
        normalized = value.strip("/")
        if ".." in normalized.split("/"):
            raise ValueError("attachment S3 prefix cannot contain parent traversal")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()

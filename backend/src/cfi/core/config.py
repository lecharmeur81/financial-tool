"""Configuration management.

All configuration comes from environment variables prefixed ``CFI_`` (R9: no secrets in code).
Connection URLs are ``SecretStr`` so they never appear in logs, reprs, or error messages.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cfi import __version__

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Application settings, validated at startup. Missing required values fail fast."""

    model_config = SettingsConfigDict(
        env_prefix="CFI_",
        # Docker Compose / the shell provide the environment; no implicit .env loading.
        env_file=None,
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "development"
    app_name: str = "Capital Flow Intelligence API"
    version: str = __version__

    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # Required — no defaults, so a missing value is a startup error, never a silent fallback.
    database_url: SecretStr
    redis_url: SecretStr

    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("database_url")
    @classmethod
    def _database_url_uses_psycopg(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("CFI_DATABASE_URL must use the 'postgresql+psycopg://' driver prefix")
        return value

    @field_validator("redis_url")
    @classmethod
    def _redis_url_scheme(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith(("redis://", "rediss://")):
            raise ValueError("CFI_REDIS_URL must start with redis:// or rediss://")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (read once from the environment)."""
    return Settings()  # values come from the environment

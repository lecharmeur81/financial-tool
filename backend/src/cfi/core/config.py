"""Configuration management.

All configuration comes from environment variables prefixed ``CFI_`` (R9: no secrets in code).
Connection URLs are ``SecretStr`` so they never appear in logs, reprs, or error messages.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
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

    # Raw payload archive (L0, ADR-0019). Relative paths resolve from the working directory.
    raw_archive_dir: Path = Path("data/raw")

    # Market data (Phase 5). Comma-separated provider IDs the workers ingest from.
    market_providers: str = "coinbase,kraken,binance,okx,bybit,coingecko"
    # Optional override of history depth per timeframe, e.g. "1m=7,1h=365" (days).
    market_backfill_days: str = ""

    @property
    def market_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.market_providers.split(",") if p.strip()]

    @property
    def market_backfill_overrides(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.market_backfill_days.split(","):
            if not item.strip():
                continue
            key, _, days = item.partition("=")
            out[key.strip()] = int(days)
        return out

    @field_validator("market_backfill_days")
    @classmethod
    def _backfill_days_format(cls, value: str) -> str:
        for item in value.split(","):
            if not item.strip():
                continue
            key, sep, days = item.partition("=")
            if not sep or not key.strip() or not days.strip().isdigit():
                raise ValueError("CFI_MARKET_BACKFILL_DAYS must look like '1m=7,1h=365'")
        return value

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

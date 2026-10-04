"""Configuration management.

All configuration comes from environment variables prefixed ``CFI_`` (R9: no secrets in code).
Connection URLs are ``SecretStr`` so they never appear in logs, reprs, or error messages.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # API key authentication (Phase 28, Priority 1). Optional in development/test (the frontend
    # only ever issues GETs, which are never protected) but required in production — see
    # ``_api_key_required_in_production`` below, which fails the app at startup rather than
    # serving unauthenticated mutating traffic (R3/R9: fail secure, never a silent gap).
    #
    # Phase 32 finding: ``compose.prod.yaml`` inherits ``CFI_API_KEY: ${CFI_API_KEY:-}`` from the
    # base compose file's shared anchor, so an operator who forgets to set ``CFI_API_KEY`` in
    # their ``.env`` gets the literal empty string as the container's env value, not an absent
    # variable. Pydantic would otherwise parse that into ``SecretStr("")``, which is not ``None``
    # — silently defeating both the fail-secure startup check below *and*
    # ``cfi.api.auth.require_api_key``'s ``secrets.compare_digest(supplied, "")``, which accepts a
    # blank ``X-API-Key`` header. Treating a blank/whitespace value as unset closes that gap at
    # the single point every other check already trusts.
    api_key: SecretStr | None = None

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_api_key_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    # Database privilege-separation (Phase 28, Priority 6). Optional, additive, opt-in: when
    # unset, the API/worker use ``database_url`` exactly as before. When set, the API/worker use
    # this (expected to be a lower-privileged runtime role) for their engine; migrations always
    # use ``database_url`` (the migration role) regardless, since this field is never read by
    # ``migrations/env.py``.
    database_url_runtime: SecretStr | None = None

    # Raw payload archive (L0, ADR-0019). Relative paths resolve from the working directory.
    raw_archive_dir: Path = Path("data/raw")

    # Market data (Phase 5). Comma-separated provider IDs the workers ingest from.
    market_providers: str = "coinbase,kraken,binance,okx,bybit,coingecko"
    # Optional override of history depth per timeframe, e.g. "1m=7,1h=365" (days).
    market_backfill_days: str = ""

    # Institutional capital (Phase 6). Comma-separated provider IDs the workers ingest from.
    # SoSoValue needs a free API key (CFI_PROVIDER_SOSOVALUE_API_KEY); without it, its jobs are
    # skipped and the dashboard says so.
    institutional_providers: str = "sosovalue,coingecko"

    # Whale intelligence (Phase 7). Comma-separated provider IDs the workers ingest from. Both
    # work without a key (Blockchair: optional CFI_PROVIDER_BLOCKCHAIR_API_KEY).
    whale_providers: str = "coinmetrics,blockchair"

    @property
    def whale_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.whale_providers.split(",") if p.strip()]

    # Derivatives (Phase 8). Comma-separated provider IDs the workers ingest from. All three
    # use public endpoints without a key.
    derivative_providers: str = "binance_futures,okx_derivatives,deribit"

    @property
    def derivative_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.derivative_providers.split(",") if p.strip()]

    # Liquidity / stablecoins (Phase 9). Comma-separated provider IDs the workers ingest from.
    # DefiLlama uses a public endpoint without a key.
    liquidity_providers: str = "defillama"

    @property
    def liquidity_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.liquidity_providers.split(",") if p.strip()]

    # Retail activity intelligence (Phase 10). Both extend providers already used by earlier
    # phases (CoinGecko, Blockchair) with one new endpoint each; no new provider or key needed.
    retail_providers: str = "coingecko,blockchair"

    @property
    def retail_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.retail_providers.split(",") if p.strip()]

    # Macro environment (Phase 11). Comma-separated provider IDs the workers ingest from. FRED
    # needs a free API key (CFI_PROVIDER_FRED_API_KEY, required — unlike every optional-key
    # provider in this project except SoSoValue); without it, its jobs are skipped and the
    # dashboard says so.
    macro_providers: str = "fred"

    @property
    def macro_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.macro_providers.split(",") if p.strip()]

    # Market structure (Phase 12). CoinGecko's existing adapter (Phase 5/6) extended with one new
    # endpoint (/global, for TOTAL market cap); no new provider or key needed. Everything else
    # (moving averages, RSI, ATR, volatility, breadth, dominance, ETH/BTC, the Market Structure
    # Score) is calculated from already-ingested Phase 5 OHLCV bars and market caps — no ingestion
    # of its own.
    market_structure_providers: str = "coingecko"

    @property
    def market_structure_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.market_structure_providers.split(",") if p.strip()]

    @property
    def market_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.market_providers.split(",") if p.strip()]

    @property
    def institutional_provider_ids(self) -> list[str]:
        return [p.strip() for p in self.institutional_providers.split(",") if p.strip()]

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

    # AI Analyst (Phase 21, ADR-0034/0068). Optional: without a key, analyst tasks are skipped
    # (not failed) — same "credential not configured" posture as SoSoValue/FRED. Model, base URL
    # and token ceiling are configuration, never hard-coded (R9, ARCHITECTURE.md 5.17).
    anthropic_api_key: SecretStr | None = None
    anthropic_api_base_url: str = "https://api.anthropic.com"
    anthropic_api_version: str = "2023-06-01"
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = Field(default=4096, ge=1, le=32000)
    anthropic_timeout_seconds: float = Field(default=60.0, gt=0)
    anthropic_rate_limit_requests: int = Field(default=50, ge=1)
    anthropic_rate_limit_per_seconds: float = Field(default=60.0, gt=0)
    # B3 (TODO.md Part B, approved 2026-09-23): a small fixed monthly ceiling; the AI pauses (with
    # an explicit, visible notice — never a silent skip) once this month's recorded ``ai.usage``
    # cost meets or exceeds it.
    ai_monthly_budget_usd: float = Field(default=20.0, ge=0)
    # Estimated cost only (``ai.usage.cost_usd`` — Section 13's "latency/token usage"); Anthropic's
    # own billing is the source of truth for actual charges. Configurable, never hard-coded into the
    # calculation itself, since list prices change over time (R9/R13).
    anthropic_input_cost_per_mtok_usd: float = Field(default=3.0, ge=0)
    anthropic_output_cost_per_mtok_usd: float = Field(default=15.0, ge=0)

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

    @field_validator("database_url_runtime")
    @classmethod
    def _database_url_runtime_uses_psycopg(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        url = value.get_secret_value()
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError(
                "CFI_DATABASE_URL_RUNTIME must use the 'postgresql+psycopg://' driver prefix"
            )
        return value

    @model_validator(mode="after")
    def _api_key_required_in_production(self) -> Settings:
        """Fail-secure (R3/R9): a production deployment with no API key configured would serve
        every mutating endpoint unauthenticated. Refuse to boot instead of serving that traffic —
        caught here, at settings construction, which runs before the app (or any worker) starts."""
        if self.environment == "production" and self.api_key is None:
            raise ValueError("CFI_API_KEY must be set when CFI_ENVIRONMENT=production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (read once from the environment)."""
    return Settings()  # values come from the environment

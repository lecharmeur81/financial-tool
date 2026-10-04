"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from cfi.api.limiter import limiter
from cfi.core.config import Settings, get_settings

TEST_DATABASE_URL = "postgresql+psycopg://user:not-a-real-password@localhost:5432/cfi_test"
TEST_REDIS_URL = "redis://:not-a-real-password@localhost:6379/0"


@pytest.fixture
def settings() -> Settings:
    """Settings for tests that must not touch real services."""
    return Settings(
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        redis_url=SecretStr(TEST_REDIS_URL),
        log_format="json",
        health_check_timeout_seconds=0.5,
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    """The rate limiter (Phase 28, Priority 2) is one process-wide instance shared by every
    ``create_app()`` call (slowapi decorators are applied once, at route-module import time), so
    its in-memory hit counters must be reset between tests or one test's requests would count
    against another's limit."""
    limiter.reset()
    yield
    limiter.reset()

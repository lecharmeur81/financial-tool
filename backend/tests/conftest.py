"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import SecretStr

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

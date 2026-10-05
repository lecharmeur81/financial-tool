"""The integration-test database is always a ``_test`` database, never the runtime one.

Regression test for a data-loss hazard: ``cfi.db.engine.create_engine`` prefers
``CFI_DATABASE_URL_RUNTIME`` over ``CFI_DATABASE_URL``, and the integration fixtures only replaced
``database_url``, so with a runtime URL set in ``.env`` the ``db`` fixture's ``TRUNCATE`` ran
against the runtime database. These tests never connect to PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings, get_settings
from tests.integration.conftest import (
    RUNTIME_URL_ENV,
    engine_database_name,
    isolated_database_env,
    isolated_settings,
    require_test_database,
    reset_test_database,
)

RUNTIME_DB = "postgresql+psycopg://runtime_role:not-a-real-password@db:5432/cfi"
MAIN_DB = "postgresql+psycopg://admin:not-a-real-password@db:5432/cfi"
TEST_DB = "postgresql+psycopg://admin:not-a-real-password@db:5432/cfi_test"
REDIS = "redis://:not-a-real-password@redis:6379/0"


def _settings(runtime: str | None) -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr(MAIN_DB),
        database_url_runtime=None if runtime is None else SecretStr(runtime),
        redis_url=SecretStr(REDIS),
    )


def test_the_runtime_url_beats_database_url_in_an_unisolated_settings_object() -> None:
    """The root cause, stated as a fact: swapping only ``database_url`` is not enough."""
    swapped = _settings(RUNTIME_DB).model_copy(update={"database_url": SecretStr(TEST_DB)})
    assert engine_database_name(swapped) == "cfi"  # still the runtime database


def test_isolated_settings_target_the_test_database_even_when_a_runtime_url_is_set() -> None:
    settings = isolated_settings(_settings(RUNTIME_DB), TEST_DB, Path("raw"))
    assert settings.database_url_runtime is None
    assert engine_database_name(settings) == "cfi_test"


def test_isolated_environment_removes_the_runtime_url_and_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CFI_DATABASE_URL", MAIN_DB)
    monkeypatch.setenv(RUNTIME_URL_ENV, RUNTIME_DB)
    monkeypatch.setenv("CFI_REDIS_URL", REDIS)
    get_settings.cache_clear()
    assert engine_database_name(get_settings()) == "cfi"  # before: the runtime database

    with isolated_database_env(TEST_DB):
        assert RUNTIME_URL_ENV not in os.environ
        assert engine_database_name(get_settings()) == "cfi_test"

    assert os.environ["CFI_DATABASE_URL"] == MAIN_DB
    assert os.environ[RUNTIME_URL_ENV] == RUNTIME_DB
    get_settings.cache_clear()
    assert engine_database_name(get_settings()) == "cfi"


def test_isolated_environment_leaves_an_unset_runtime_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CFI_DATABASE_URL", MAIN_DB)
    monkeypatch.delenv(RUNTIME_URL_ENV, raising=False)
    with isolated_database_env(TEST_DB):
        assert RUNTIME_URL_ENV not in os.environ
    assert RUNTIME_URL_ENV not in os.environ


@pytest.mark.parametrize("name", ["cfi", "cfi_runtime", "postgres", "", "cfi_test_backup"])
def test_a_non_test_database_name_is_refused(name: str) -> None:
    with pytest.raises(RuntimeError, match="Refusing to run destructive"):
        require_test_database(name)


def test_a_test_database_name_is_accepted() -> None:
    require_test_database("cfi_test")
    require_test_database("anything_test")


class _Result:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _Conn:
    def __init__(self, database: str) -> None:
        self.database = database
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.database)


class _Begin:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeEngine:
    def __init__(self, database: str) -> None:
        self.conn = _Conn(database)

    def begin(self) -> _Begin:
        return _Begin(self.conn)


async def test_the_reset_never_truncates_a_non_test_database() -> None:
    fake = _FakeEngine("cfi")  # the engine is connected to the runtime database
    with pytest.raises(RuntimeError, match="Refusing to run destructive"):
        await reset_test_database(cast(AsyncEngine, fake))
    assert fake.conn.statements == ["SELECT current_database()"]  # no TRUNCATE was issued


async def test_the_reset_truncates_a_test_database() -> None:
    fake = _FakeEngine("cfi_test")
    await reset_test_database(cast(AsyncEngine, fake))
    assert fake.conn.statements[0] == "SELECT current_database()"
    assert fake.conn.statements[1].startswith("TRUNCATE ")
    assert "ai.snapshot" in fake.conn.statements[1]

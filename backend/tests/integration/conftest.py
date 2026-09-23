"""Integration fixtures.

Data-writing tests never touch the configured database. They run in a separate database named
``<configured name>_test`` on the same server, recreated and migrated once per test session.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings, get_settings
from cfi.db.engine import create_engine

BACKEND = Path(__file__).resolve().parents[2]
SERVICES_AVAILABLE = bool(os.environ.get("CFI_DATABASE_URL") and os.environ.get("CFI_REDIS_URL"))
requires_services = pytest.mark.skipif(
    not SERVICES_AVAILABLE,
    reason="CFI_DATABASE_URL and CFI_REDIS_URL not set — integration services unavailable",
)

DATA_TABLES = (
    "ops.quality_check_result",
    "obs.observation",
    "obs.series",
    "raw.payload",
    "ops.provider_request",
    "ops.job_run",
    "ops.dataset_provider",
    "ops.dataset",
    "ops.provider",
)


def alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None
    return head


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create ``<db>_test``, migrate it to head, and yield its SQLAlchemy URL."""
    if not SERVICES_AVAILABLE:
        pytest.skip("integration services unavailable")
    main = make_url(os.environ["CFI_DATABASE_URL"])
    test_name = f"{main.database}_test"
    admin = main.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{test_name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{test_name}"')
    url = main.set(database=test_name).render_as_string(hide_password=False)

    previous = os.environ["CFI_DATABASE_URL"]
    os.environ["CFI_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(), "head")
        yield url
    finally:
        os.environ["CFI_DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture
def test_settings(test_database_url: str, tmp_path: Path) -> Settings:
    return get_settings().model_copy(
        update={"database_url": SecretStr(test_database_url), "raw_archive_dir": tmp_path / "raw"}
    )


@pytest.fixture
async def db(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Async engine on the test database, emptied before each test."""
    engine = create_engine(test_settings)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()

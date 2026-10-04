"""Integration fixtures.

Data-writing tests never touch the configured database. They run in a separate database named
``<configured name>_test`` on the same server, recreated and migrated once per test session.
"""

from __future__ import annotations

import asyncio
import os
import sys
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

# Windows test-environment-only: psycopg's async mode does not support the ProactorEventLoop
# asyncio uses by default on Windows (it needs ``loop.add_reader``/socket-waiter support the
# Proactor implementation does not provide), and raises ``psycopg.InterfaceError`` the moment an
# async connection is opened. Every integration test opens one (directly, via the ``db`` fixture's
# async engine, or via Alembic's online migration inside ``test_database_url``), so the policy
# must be set before any event loop is created — plain module-level code at import time, not a
# pytest-asyncio fixture/hook override (overriding the "event_loop_policy" fixture itself is
# deprecated in pytest-asyncio 1.x; this never touches that fixture, so no deprecation warning).
# A no-op everywhere else: ``WindowsSelectorEventLoopPolicy`` only exists on win32, and nothing
# about Python 3.12 support, asyncio_mode, or loop scope changes on any platform.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND = Path(__file__).resolve().parents[2]
SERVICES_AVAILABLE = bool(os.environ.get("CFI_DATABASE_URL") and os.environ.get("CFI_REDIS_URL"))
requires_services = pytest.mark.skipif(
    not SERVICES_AVAILABLE,
    reason="CFI_DATABASE_URL and CFI_REDIS_URL not set — integration services unavailable",
)

DATA_TABLES = (
    "usr.decision_journal",
    "usr.paper_trade",
    "usr.alert_event",
    "ai.usage",
    "ai.interpretation",
    "ai.snapshot",
    "ops.quality_check_result",
    "ops.backfill_state",
    "obs.institutional_flow",
    "obs.large_transfer",
    "ref.entity_label",
    "ref.entity",
    "obs.market_bar",
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


# Market-data harness fixture (defined with its helpers in market_support.py).
from tests.integration.derivative_support import deriv  # noqa: E402, F401
from tests.integration.institutional_support import inst  # noqa: E402, F401
from tests.integration.liquidity_support import liquidity  # noqa: E402, F401
from tests.integration.macro_support import macro  # noqa: E402, F401
from tests.integration.market_structure_support import market_structure  # noqa: E402, F401
from tests.integration.market_support import market  # noqa: E402, F401
from tests.integration.retail_support import retail  # noqa: E402, F401
from tests.integration.whale_support import whales  # noqa: E402, F401

"""Integration fixtures.

Data-writing tests never touch the configured database. They run in a separate database named
``<configured name>_test`` on the same server, recreated and migrated once per test session.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
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


RUNTIME_URL_ENV = "CFI_DATABASE_URL_RUNTIME"


@contextmanager
def isolated_database_env(test_url: str) -> Iterator[None]:
    """Point the process environment at the test database and nothing else.

    ``CFI_DATABASE_URL`` becomes the test URL **and** ``CFI_DATABASE_URL_RUNTIME`` is removed.
    ``cfi.db.engine.create_engine`` prefers the runtime URL when one is set, so swapping only
    ``CFI_DATABASE_URL`` (as this fixture once did) leaves every engine built from
    ``get_settings()`` pointing at the runtime database whenever ``.env`` sets a runtime role.
    Both variables are restored on exit."""
    saved = {name: os.environ.get(name) for name in ("CFI_DATABASE_URL", RUNTIME_URL_ENV)}
    os.environ["CFI_DATABASE_URL"] = test_url
    os.environ.pop(RUNTIME_URL_ENV, None)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def isolated_settings(base: Settings, test_url: str, raw_dir: Path) -> Settings:
    """``base`` re-pointed at the test database. The runtime URL is cleared explicitly: it is
    what ``create_engine`` would otherwise use in preference to ``database_url``."""
    return base.model_copy(
        update={
            "database_url": SecretStr(test_url),
            "database_url_runtime": None,
            "raw_archive_dir": raw_dir,
        }
    )


def engine_database_name(settings: Settings) -> str:
    """The database ``create_engine(settings)`` would connect to (the runtime URL wins)."""
    url = settings.database_url_runtime or settings.database_url
    return make_url(url.get_secret_value()).database or ""


def require_test_database(name: str) -> None:
    """Refuse to continue unless ``name`` is a test database (``<configured name>_test``)."""
    if not name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run destructive integration-test setup against database {name!r}: "
            "integration tests may only use a database whose name ends in '_test'."
        )


async def reset_test_database(engine: AsyncEngine) -> None:
    """Empty every data table. The connected database is checked first, in the same transaction
    and before any statement that changes data, so a mis-pointed engine fails loudly instead of
    truncating a real database."""
    async with engine.begin() as conn:
        name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        require_test_database(str(name))
        await conn.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"))


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

    with isolated_database_env(url):
        command.upgrade(alembic_config(), "head")
        yield url


@pytest.fixture
def test_settings(test_database_url: str, tmp_path: Path) -> Settings:
    return isolated_settings(get_settings(), test_database_url, tmp_path / "raw")


@pytest.fixture
async def db(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Async engine on the test database, emptied before each test."""
    require_test_database(engine_database_name(test_settings))
    engine = create_engine(test_settings)
    try:
        await reset_test_database(engine)
    except BaseException:
        await engine.dispose()
        raise
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

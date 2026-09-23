"""Integration tests against real PostgreSQL+TimescaleDB and Redis.

Run with the services available and ``CFI_DATABASE_URL`` / ``CFI_REDIS_URL`` set, e.g.
``docker compose exec api pytest -m integration``. They are skipped — visibly — when the
URLs are absent.
Migrations must have been applied (``alembic upgrade head``) before running them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.api.app import create_app
from cfi.cache.redis import check_redis, create_redis
from cfi.core.config import Settings, get_settings
from cfi.db.engine import LAYER_SCHEMAS, check_database, create_engine
from tests.integration.conftest import head_revision

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("CFI_DATABASE_URL") and os.environ.get("CFI_REDIS_URL")),
        reason="CFI_DATABASE_URL and CFI_REDIS_URL not set — integration services unavailable",
    ),
]


@pytest.fixture
def live_settings() -> Settings:
    return get_settings()


@pytest.fixture
async def engine(live_settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(live_settings)
    yield eng
    await eng.dispose()


async def test_timescaledb_installed_and_migrated(engine: AsyncEngine) -> None:
    detail = await check_database(engine)
    assert detail["timescaledb_version"] != "not_installed"
    assert detail["schema_revision"] == head_revision()
    assert detail["session_timezone"] == "UTC"


async def test_layer_schemas_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(:s)"),
            {"s": list(LAYER_SCHEMAS)},
        )
        found = {r[0] for r in rows}
    assert found == set(LAYER_SCHEMAS)


async def test_hypertable_can_be_created_in_a_transaction(engine: AsyncEngine) -> None:
    """Proves TimescaleDB works end to end; rolled back, so nothing persists."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(
                text("CREATE TABLE ops._probe (at timestamptz NOT NULL, v numeric NOT NULL)")
            )
            await conn.execute(text("SELECT create_hypertable('ops._probe', 'at')"))
            is_ht = await conn.scalar(
                text(
                    "SELECT count(*) FROM timescaledb_information.hypertables "
                    "WHERE hypertable_schema = 'ops' AND hypertable_name = '_probe'"
                )
            )
            assert is_ht == 1
        finally:
            await trans.rollback()


async def test_redis_roundtrip(live_settings: Settings) -> None:
    client = create_redis(live_settings)
    try:
        detail = await check_redis(client)
        assert detail["ping"] == "PONG"
        await client.set("cfi:test:probe", "1", ex=5)
        assert await client.get("cfi:test:probe") == "1"
        await client.delete("cfi:test:probe")
    finally:
        await client.aclose()


def test_ready_endpoint_against_real_services(live_settings: Settings) -> None:
    with TestClient(create_app(live_settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["components"]["database"]["detail"]["schema_revision"] == head_revision()
    assert body["components"]["redis"]["detail"]["ping"] == "PONG"

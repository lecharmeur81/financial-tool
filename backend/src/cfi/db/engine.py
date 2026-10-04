"""Database connection (PostgreSQL + TimescaleDB via psycopg 3, SQLAlchemy async)."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cfi.core.config import Settings

LAYER_SCHEMAS: tuple[str, ...] = ("ref", "raw", "obs", "calc", "sig", "regime", "ai", "usr", "ops")


def create_engine(settings: Settings) -> AsyncEngine:
    # Database privilege separation (Phase 28, Priority 6): opt-in runtime URL, intended for a
    # lower-privileged role. Unset (the default) falls back to ``database_url`` exactly as before
    # this setting existed — zero behavior change for every existing deployment. Migrations never
    # call this function (``migrations/env.py`` reads ``settings.database_url`` directly), so a
    # restricted runtime role here can never run a migration.
    url = settings.database_url_runtime or settings.database_url
    return create_async_engine(
        url.get_secret_value(),
        pool_size=settings.db_pool_size,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC"},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:  # type: ignore[type-arg]
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> Mapping[str, str]:
    """Readiness check: reachable, TimescaleDB installed, migration revision, session time zone."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        ts_version = await conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        has_version_table = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
        revision = (
            await conn.scalar(text("SELECT version_num FROM alembic_version"))
            if has_version_table is not None
            else None
        )
        tz = await conn.scalar(text("SHOW timezone"))
    return {
        "timescaledb_version": str(ts_version) if ts_version else "not_installed",
        "schema_revision": str(revision) if revision else "not_migrated",
        "session_timezone": str(tz),
    }

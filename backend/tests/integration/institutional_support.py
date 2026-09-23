"""Institutional test harness: real adapters, engine, jobs and database; fake provider servers
serving the synthetic historical fixtures (tests/fixtures/institutional)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.institutional.jobs import ingest_source
from cfi.institutional.sources import ADAPTERS, PRIORITY, SOURCES, source
from cfi.market.jobs import JobContext
from cfi.providers import coingecko, sosovalue
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.institutional_fakes import CoinGeckoTreasuryFake, SoSoValueFake
from tests.support import FakeClock, WallClock

# Wednesday after Labor Day: the latest trading day due is Friday 2026-09-04 (README).
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@dataclass
class InstitutionalHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    soso: SoSoValueFake
    gecko: CoinGeckoTreasuryFake
    ctx: JobContext

    async def run(self, provider_id: str, dataset_id: str) -> list[IngestionResult]:
        return await ingest_source(self.ctx, source(provider_id, dataset_id))

    async def run_all(self) -> None:
        for item in SOURCES:
            await ingest_source(self.ctx, item)

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


@pytest.fixture
async def inst(db: AsyncEngine, test_settings: Settings) -> InstitutionalHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    soso, gecko = SoSoValueFake(), CoinGeckoTreasuryFake()
    environ = {sosovalue.API_KEY_ENV: "test-key"}
    clients = {
        pid: ProviderHttpClient(
            ADAPTERS[pid].capabilities,
            transport=fake.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.5, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ=environ,
            sleep=ticks.sleep,
            clock=ticks,
        )
        for pid, fake in ((sosovalue.PROVIDER_ID, soso), (coingecko.PROVIDER_ID, gecko))
    }
    for item in SOURCES:
        await engine.register(item.dataset, ADAPTERS[item.provider_id], PRIORITY[item.provider_id])
    ctx = JobContext(engine, db, clients, wall)
    return InstitutionalHarness(db, wall, ticks, engine, soso, gecko, ctx)


FLOWS_SQL = """
    SELECT s.asset, s.subject_ref, s.period, f.*
      FROM obs.institutional_flow f JOIN obs.series s USING (series_id)
     WHERE s.dataset_id = :d
     ORDER BY s.subject_ref, f.event_time, f.revision
"""

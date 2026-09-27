"""Market-structure test harness: the real CoinGecko adapter's ``/global`` extension, engine, jobs
and database, against the in-process fake CoinGecko global-data server
(``tests/market_structure_fakes.py``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.market_structure.jobs import ingest_source
from cfi.market_structure.sources import ADAPTERS, PRIORITY, SOURCES, MarketStructureSource
from cfi.market_structure.universe import all_datasets
from cfi.providers import coingecko
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.market_structure_fakes import CoinGeckoGlobalFake
from tests.support import FakeClock, WallClock

NOW = datetime(2026, 9, 27, tzinfo=UTC)


@dataclass
class MarketStructureHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    coingecko: CoinGeckoGlobalFake
    ctx: JobContext

    def source(self, dataset_id: str) -> MarketStructureSource:
        return next(s for s in SOURCES if s.dataset.dataset_id == dataset_id)

    async def run(self, item: MarketStructureSource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def load(self, dataset_id: str) -> list[IngestionResult]:
        item = self.source(dataset_id)
        return await self.run(item)


@pytest.fixture
async def market_structure(db: AsyncEngine, test_settings: Settings) -> MarketStructureHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    fake = CoinGeckoGlobalFake(wall)
    clients = {
        coingecko.PROVIDER_ID: ProviderHttpClient(
            ADAPTERS[coingecko.PROVIDER_ID].capabilities,
            transport=fake.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        ),
    }
    for dataset in all_datasets():
        await engine.register(
            dataset, ADAPTERS[coingecko.PROVIDER_ID], PRIORITY[coingecko.PROVIDER_ID]
        )
    ctx = JobContext(engine, db, clients, wall)
    return MarketStructureHarness(db, wall, ticks, engine, fake, ctx)

"""Market-data test harness: real adapters, engine, jobs and database; fake provider servers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.market.sources import ADAPTERS, PRIORITY, datasets_for
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.market_fakes import (
    BinanceFake,
    BybitFake,
    CoinbaseFake,
    CoinGeckoFake,
    FakeProvider,
    KrakenFake,
    OkxFake,
)
from tests.support import FakeClock, WallClock

NOW = datetime(2026, 9, 1, 12, 0, 30, tzinfo=UTC)


@dataclass
class MarketHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    fakes: dict[str, FakeProvider]
    ctx: JobContext

    async def register(self) -> None:
        for provider_id in self.fakes:
            for dataset in datasets_for(provider_id):
                await self.engine.register(dataset, ADAPTERS[provider_id], PRIORITY[provider_id])

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


@pytest.fixture
async def market(db: AsyncEngine, test_settings: Settings) -> MarketHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    fakes: dict[str, FakeProvider] = {
        "coinbase": CoinbaseFake(wall),
        "binance": BinanceFake(wall),
        "kraken": KrakenFake(wall),
        "okx": OkxFake(wall),
        "bybit": BybitFake(wall),
        "coingecko": CoinGeckoFake(wall),
    }
    clients = {
        pid: ProviderHttpClient(
            ADAPTERS[pid].capabilities,
            transport=fake.transport(),
            retry=RetryPolicy(max_attempts=3, base_delay=0.5, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        )
        for pid, fake in fakes.items()
    }
    harness = MarketHarness(db, wall, ticks, engine, fakes, JobContext(engine, db, clients, wall))
    await harness.register()
    return harness


BARS_SQL = """
    SELECT s.asset, s.unit, s.venue, s.subject_ref, s.period, b.*
      FROM obs.market_bar b JOIN obs.series s USING (series_id)
     WHERE s.dataset_id = :d AND s.asset = :a
     ORDER BY b.event_time, b.revision
"""

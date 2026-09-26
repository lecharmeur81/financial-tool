"""Liquidity test harness: real adapter, engine, jobs and database; a fake DefiLlama server
serving the synthetic history of ``tests/liquidity_fakes.py``."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.liquidity.jobs import ingest_source
from cfi.liquidity.sources import ADAPTERS, PRIORITY, SOURCES, LiquiditySource
from cfi.market.jobs import JobContext
from cfi.providers import defillama
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.liquidity_fakes import NOW, DefiLlamaFake
from tests.support import FakeClock, WallClock


@dataclass
class LiquidityHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    fake: DefiLlamaFake
    ctx: JobContext

    def source(self, subject: str) -> LiquiditySource:
        return next(s for s in SOURCES if s.subject == subject)

    async def run(self, item: LiquiditySource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def load_everything(self) -> None:
        """One run per subject: the recent window (last 3 days) plus the first history chunk
        (180 days back) together already span the fake's entire ~56-day synthetic history, since
        DefiLlama's real (and fake) endpoint always returns its whole history in one response —
        ``parse_page`` just filters each requested window client-side (``providers/defillama.py``).
        """
        for subject in ("USDT", "USDC", "TOTAL"):
            await self.run(self.source(subject))


@pytest.fixture
async def liquidity(
    db: AsyncEngine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> LiquidityHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    fake = DefiLlamaFake()
    client = ProviderHttpClient(
        ADAPTERS[defillama.PROVIDER_ID].capabilities,
        transport=fake.transport(),
        retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
        recorder=RepositoryRecorder(repo),
        environ={},
        sleep=ticks.sleep,
        clock=ticks,
    )
    for item in SOURCES:
        await engine.register(item.dataset, ADAPTERS[item.provider_id], PRIORITY[item.provider_id])
    ctx = JobContext(engine, db, {defillama.PROVIDER_ID: client}, wall)
    return LiquidityHarness(db, wall, ticks, engine, fake, ctx)

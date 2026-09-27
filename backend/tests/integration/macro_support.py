"""Macro test harness: the real FRED adapter, engine, jobs and database, against the in-process
fake FRED server (``tests/macro_fakes.py``)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.macro.jobs import ingest_source
from cfi.macro.sources import ADAPTERS, PRIORITY, SOURCES, MacroSource
from cfi.macro.universe import all_datasets
from cfi.market.jobs import JobContext
from cfi.providers import fred
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.macro_fakes import NOW, FredFake
from tests.support import FakeClock, WallClock


@dataclass
class MacroHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    fred: FredFake
    ctx: JobContext

    def source(self, dataset_id: str) -> MacroSource:
        return next(s for s in SOURCES if s.dataset.dataset_id == dataset_id)

    async def run(self, item: MacroSource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def load(self, dataset_id: str, history_runs: int = 1) -> list[IngestionResult]:
        """One recent-window run plus ``history_runs`` history-chunk runs for one dataset."""
        item = self.source(dataset_id)
        return await self.run(item, times=1 + history_runs)


@pytest.fixture
async def macro(
    db: AsyncEngine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> MacroHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    fake = FredFake()
    clients = {
        fred.PROVIDER_ID: ProviderHttpClient(
            ADAPTERS[fred.PROVIDER_ID].capabilities,
            transport=fake.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={fred.API_KEY_ENV: "test-key"},
            sleep=ticks.sleep,
            clock=ticks,
        ),
    }
    for dataset in all_datasets():
        await engine.register(dataset, ADAPTERS[fred.PROVIDER_ID], PRIORITY[fred.PROVIDER_ID])
    ctx = JobContext(engine, db, clients, wall)
    return MacroHarness(db, wall, ticks, engine, fake, ctx)

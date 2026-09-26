"""Retail test harness: real adapters, engine, jobs and database for the two datasets this phase
adds (CoinGecko trending, Blockchair small-output-count); the two derivatives datasets it reads
cross-module (funding rate, long/short account ratio) are inserted directly as canonical records,
exactly like ``tests/integration/derivative_support.py``'s ``store_market_inputs`` does for its
own read-only "context" inputs (Coinbase bars, CoinGecko market caps) — a deliberate, established
pattern for context data that is not itself the module's new work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.derivatives.sources import ADAPTERS as DERIVATIVES_ADAPTERS
from cfi.derivatives.sources import PRIORITY as DERIVATIVES_PRIORITY
from cfi.derivatives.universe import FUNDING_RATE, LONG_SHORT_RATIO, perp_ref
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.providers import binance_futures, blockchair, coingecko
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from cfi.retail.jobs import ingest_source
from cfi.retail.sources import ADAPTERS, PRIORITY, SOURCES, RetailSource
from tests.retail_fakes import NOW, BlockchairSmallOutputFake, CoinGeckoTrendingFake
from tests.support import FakeClock, WallClock

H = timedelta(hours=1)
# Funding/ratio synthetic history: BTC and ETH populated, SOL and XRP left empty on purpose
# (Insufficient data / partial-weight checks), mirroring derivatives' own test convention.
DERIVATIVES_ASSETS = ("BTC", "ETH")
DERIVATIVES_HISTORY = timedelta(days=10)


def funding_rate(asset: str, hour_index: int) -> Decimal:
    """A small oscillation around zero, asset-shifted so BTC and ETH never coincide exactly."""
    base = Decimal("0.0002") if asset == "BTC" else Decimal("-0.00015")
    swing = Decimal("0.0001") * (1 if hour_index % 2 == 0 else -1)
    return base + swing


def account_ratio(asset: str, hour_index: int) -> Decimal:
    """1.0 +/- a small, asset-shifted, hour-varying deviation."""
    base = Decimal("1.20") if asset == "BTC" else Decimal("0.85")
    drift = Decimal("0.01") * (hour_index % 5)
    return base + drift


@dataclass
class RetailHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    trending: CoinGeckoTrendingFake
    small_output: BlockchairSmallOutputFake
    ctx: JobContext

    def source(self, provider_id: str, dataset_id: str, subject: str) -> RetailSource:
        return next(
            s
            for s in SOURCES
            if s.provider_id == provider_id
            and s.dataset.dataset_id == dataset_id
            and s.subject == subject
        )

    async def run(self, item: RetailSource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def store_derivatives_inputs(self) -> None:
        """Direct-insert synthetic funding-rate and long/short-account-ratio rows for BTC and ETH
        (see module docstring for why this bypasses the derivatives adapter)."""
        stores = self.engine._stores
        repo = self.engine.repo
        for asset in DERIVATIVES_ASSETS:
            funding_rows = []
            ratio_rows = []
            t = NOW - DERIVATIVES_HISTORY
            i = 0
            while t < NOW:
                funding_rows.append(
                    CanonicalObservation(
                        dataset_id=FUNDING_RATE.dataset_id,
                        metric=FUNDING_RATE.metric,
                        asset=asset,
                        subject_ref=perp_ref(asset),
                        venue="binance",
                        period=FUNDING_RATE.period,
                        unit=FUNDING_RATE.unit,
                        event_time=t,
                        available_at=t + timedelta(minutes=1),
                        available_at_estimated=True,
                        ingested_at=t + timedelta(minutes=1),
                        source_provider="binance_futures",
                        original_source="binance",
                        quality_status=QualityStatus.OK,
                        pit_reliability=PitReliability.NATIVE,
                        value=funding_rate(asset, i),
                    )
                )
                ratio_rows.append(
                    CanonicalObservation(
                        dataset_id=LONG_SHORT_RATIO.dataset_id,
                        metric=LONG_SHORT_RATIO.metric,
                        asset=asset,
                        subject_ref=perp_ref(asset),
                        venue="binance",
                        period=LONG_SHORT_RATIO.period,
                        unit=LONG_SHORT_RATIO.unit,
                        event_time=t,
                        available_at=t + timedelta(minutes=1),
                        available_at_estimated=True,
                        ingested_at=t + timedelta(minutes=1),
                        source_provider="binance_futures",
                        original_source="binance",
                        quality_status=QualityStatus.OK,
                        pit_reliability=PitReliability.NATIVE,
                        value=account_ratio(asset, i),
                    )
                )
                t += H
                i += 1
            sid = await repo.series_id(funding_rows[0])
            await stores["scalar"].insert([(sid, r) for r in funding_rows])
            sid = await repo.series_id(ratio_rows[0])
            await stores["scalar"].insert([(sid, r) for r in ratio_rows])

    async def load_trending(self, polls: int, step: timedelta = timedelta(hours=6)) -> None:
        """Advance the wall clock and poll the trending source ``polls`` times (there is no
        history to backfill — each poll is a live snapshot, see retail/sources.py)."""
        [item] = [s for s in SOURCES if s.provider_id == coingecko.PROVIDER_ID]
        start = NOW - step * polls
        self.wall.current = start
        for _ in range(polls):
            self.wall.current += step
            await self.run(item)

    async def load_small_output_count(self) -> None:
        """One recent-window read plus enough history chunks to cover the fake's ~87-day
        synthetic history (30-day chunks; 4 runs reach 120 days back)."""
        [item] = [s for s in SOURCES if s.provider_id == blockchair.PROVIDER_ID]
        await self.run(item, times=4)


@pytest.fixture
async def retail(
    db: AsyncEngine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> RetailHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    trending = CoinGeckoTrendingFake()
    small_output = BlockchairSmallOutputFake()
    clients = {
        coingecko.PROVIDER_ID: ProviderHttpClient(
            ADAPTERS[coingecko.PROVIDER_ID].capabilities,
            transport=trending.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        ),
        blockchair.PROVIDER_ID: ProviderHttpClient(
            ADAPTERS[blockchair.PROVIDER_ID].capabilities,
            transport=small_output.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.1, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        ),
    }
    for item in SOURCES:
        await engine.register(item.dataset, ADAPTERS[item.provider_id], PRIORITY[item.provider_id])
    # Cross-module context data (see module docstring): funding rate / account ratio are owned
    # and normally registered by the derivatives module (Phase 8) — register them here too, since
    # store_derivatives_inputs() direct-inserts rows for them without going through that module's
    # own fixture (mirrors derivative_support.py's own registration of ITS context datasets).
    await engine.register(
        FUNDING_RATE,
        DERIVATIVES_ADAPTERS[binance_futures.PROVIDER_ID],
        DERIVATIVES_PRIORITY[binance_futures.PROVIDER_ID],
    )
    await engine.register(
        LONG_SHORT_RATIO,
        DERIVATIVES_ADAPTERS[binance_futures.PROVIDER_ID],
        DERIVATIVES_PRIORITY[binance_futures.PROVIDER_ID],
    )
    ctx = JobContext(engine, db, clients, wall)
    return RetailHarness(db, wall, ticks, engine, trending, small_output, ctx)

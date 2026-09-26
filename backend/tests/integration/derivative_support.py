"""Derivatives test harness: real adapters, engine, jobs and database; fake Binance futures, OKX
and Deribit servers serving the synthetic history of tests/fixtures/derivatives (README).

Coinbase hourly BTC-USD bars and CoinGecko daily market caps (inputs of the leverage ratio and the
price context) are stored directly as canonical records with the values of that README."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.derivatives.jobs import ingest_source
from cfi.derivatives.sources import ADAPTERS, PRIORITY, SOURCES, DerivativesSource
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalBar, CanonicalObservation
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import MARKET_CAP_USD_1D, ohlcv_dataset
from cfi.providers import binance_futures, coinbase, coingecko, deribit, okx_derivatives
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from tests.derivative_fakes import (
    FIRST,
    LATEST,
    NOW,
    BinanceFuturesFake,
    DeribitFake,
    OkxDerivativesFake,
)
from tests.support import FakeClock, WallClock

H = timedelta(hours=1)
ASSETS = ("BTC", "SOL")  # ETH and XRP stay empty on purpose (Insufficient data)


def price(bar_open: datetime) -> Decimal:
    """Coinbase BTC-USD hourly close: 50,000 up to the bar opening one week before the newest
    snapshot's bar, 60,000 after."""
    return Decimal(50_000) if bar_open <= LATEST - timedelta(days=7) - H else Decimal(60_000)


def market_cap(day: datetime) -> Decimal:
    return Decimal("1.2E12") if day >= datetime(2026, 9, 4, tzinfo=NOW.tzinfo) else Decimal("1E12")


@dataclass
class DerivativesHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    binance: BinanceFuturesFake
    okx: OkxDerivativesFake
    deribit: DeribitFake
    ctx: JobContext

    def sources(self, asset: str, metric: str | None = None) -> list[DerivativesSource]:
        return [
            s
            for s in SOURCES
            if s.subject == asset and (metric is None or s.dataset.metric == metric)
        ]

    async def run(self, item: DerivativesSource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def store_market_inputs(self) -> None:
        """Coinbase BTC-USD 1 h closes and CoinGecko BTC daily market caps (README)."""
        bars = ohlcv_dataset("usd", "1h")
        stores = self.engine._stores
        repo = self.engine.repo
        t = FIRST - timedelta(days=1)
        rows = []
        while t < NOW - H:
            close = price(t)
            bar = CanonicalBar(
                dataset_id=bars.dataset_id,
                metric=bars.metric,
                asset="BTC",
                subject_ref=coinbase.instrument_ref("BTC-USD"),
                venue=coinbase.VENUE,
                period="1h",
                unit="usd",
                event_time=t,
                available_at=t + H + timedelta(minutes=1),
                available_at_estimated=True,
                ingested_at=t + H + timedelta(minutes=1),
                source_provider=coinbase.PROVIDER_ID,
                original_source="coinbase",
                quality_status=QualityStatus.OK,
                pit_reliability=PitReliability.NATIVE,
                open=close,
                high=close,
                low=close,
                close=close,
                volume_base=Decimal(1),
            )
            rows.append(bar)
            t += H
        sid = await repo.series_id(rows[0])
        await stores["bar"].insert([(sid, r) for r in rows])
        caps = []
        day = FIRST.replace(hour=0, minute=0) - timedelta(days=1)
        while day < NOW:
            caps.append(
                CanonicalObservation(
                    dataset_id=MARKET_CAP_USD_1D.dataset_id,
                    metric="market_cap",
                    asset="BTC",
                    subject_ref="BTC",
                    venue=None,
                    period="1d",
                    unit="usd",
                    event_time=day,
                    available_at=day + timedelta(minutes=10),
                    available_at_estimated=True,
                    ingested_at=day + timedelta(minutes=10),
                    source_provider=coingecko.PROVIDER_ID,
                    original_source="coingecko",
                    quality_status=QualityStatus.OK,
                    pit_reliability=PitReliability.NATIVE,
                    value=market_cap(day),
                )
            )
            day += timedelta(days=1)
        sid = await repo.series_id(caps[0])
        await stores["scalar"].insert([(sid, c) for c in caps])

    async def load_everything(self) -> None:
        await self.store_market_inputs()
        # OKX keeps liquidations for about a day: collect them as the hourly job would, every
        # 12 hours over 8 days (each run reaches back to the last stored hour).
        [liquidations] = self.sources("BTC", "liquidations")
        self.wall.current = NOW - timedelta(days=8)
        while self.wall.current < NOW:
            await self.run(liquidations)
            self.wall.advance(timedelta(hours=12))
        self.wall.current = NOW
        for asset in ASSETS:
            for item in self.sources(asset):
                # enough runs to finish every history chunk (DVOL: 365 days in 40-day chunks)
                await self.run(item, times=11 if item.history else 1)

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


@pytest.fixture
async def deriv(
    db: AsyncEngine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> DerivativesHarness:
    wall = WallClock(NOW)
    # responses are timestamped by the (simulated) wall clock: OKX liquidation retention is
    # judged from the time a response was received
    monkeypatch.setattr("cfi.providers.http.utc_now", wall)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    b, o, d = BinanceFuturesFake(), OkxDerivativesFake(), DeribitFake(wall)
    transports = {
        binance_futures.PROVIDER_ID: b.transport(),
        okx_derivatives.PROVIDER_ID: o.transport(),
        deribit.PROVIDER_ID: d.transport(),
    }
    clients = {
        pid: ProviderHttpClient(
            ADAPTERS[pid].capabilities,
            transport=transport,
            retry=RetryPolicy(max_attempts=2, base_delay=0.5, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        )
        for pid, transport in transports.items()
    }
    for item in SOURCES:
        await engine.register(item.dataset, ADAPTERS[item.provider_id], PRIORITY[item.provider_id])
    await engine.register(ohlcv_dataset("usd", "1h"), MARKET_ADAPTERS[coinbase.PROVIDER_ID], 10)
    await engine.register(MARKET_CAP_USD_1D, MARKET_ADAPTERS[coingecko.PROVIDER_ID], 10)
    ctx = JobContext(engine, db, clients, wall)
    return DerivativesHarness(db, wall, ticks, engine, b, o, d, ctx)

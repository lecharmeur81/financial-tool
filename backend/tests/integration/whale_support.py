"""Whale test harness: real adapters, engine, jobs, labels and database; fake Coin Metrics and
Blockchair servers serving the synthetic history of tests/fixtures/whales (README)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.ingestion.repository import IngestionRepository, RepositoryRecorder
from cfi.market.jobs import JobContext
from cfi.providers import blockchair, coinmetrics
from cfi.providers.http import ProviderHttpClient, RetryPolicy
from cfi.whales.jobs import ingest_source
from cfi.whales.label_store import import_labels
from cfi.whales.labels import CSV_COLUMNS, parse_label_csv
from cfi.whales.sources import ADAPTERS, PRIORITY, SOURCES, WhaleSource, source
from cfi.whales.universe import dataset
from tests.support import FakeClock, WallClock
from tests.whale_fakes import (
    BlockchairFake,
    CoinMetricsFake,
    btc_address,
    btc_output,
    eth_address,
    eth_tx,
)

# In the past, so the API (which never looks beyond the real current time) sees everything.
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
SNAPSHOT_THEN = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
SNAPSHOT_NOW = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
LABELS_PUBLISHED = datetime(2026, 9, 8, 5, 29, 20, tzinfo=UTC)
# Two addresses of the shipped seed file, relabelled here in a test label file published on
# LABELS_PUBLISHED (the seed itself was published 2026-09-24, after this synthetic history).
BINANCE = "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"
UK_GOV = "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"
TEST_LABELS = "\n".join(
    [
        ",".join(CSV_COLUMNS),
        f'bitcoin,{BINANCE},exchange,binance,Binance,attributed,0.6,"Test label file: wallet label '
        f'""Binance-coldwallet""",Test labels,,,,{LABELS_PUBLISHED.isoformat()}',
        f"bitcoin,{UK_GOV},government,uk-government,United Kingdom government (seized funds),"
        f'attributed,0.6,"Test label file: wallet label ""UK-Gov-Confiscated""",Test labels,,,,'
        f"{LABELS_PUBLISHED.isoformat()}",
    ]
)
UNKNOWN = [btc_address(i) for i in range(10)]
SMALL = btc_address(99)  # below the unknown-large-holder threshold


def snapshot_then() -> dict[str, Decimal]:
    return {BINANCE: Decimal(250_000), UK_GOV: Decimal(61_000)} | {
        a: Decimal(10_000) for a in UNKNOWN
    }


def snapshot_now() -> dict[str, Decimal]:
    # unknown holders +1 %, Binance -2 %, the UK wallet unchanged; one small new address
    return {BINANCE: Decimal(245_000), UK_GOV: Decimal(61_000), SMALL: Decimal(900)} | {
        a: Decimal(10_100) for a in UNKNOWN
    }


EXCHANGE_ETH = eth_address(1)
WHALE_ETH = eth_address(2)


def transfers(fake: BlockchairFake) -> None:
    """Three BTC outputs and two ETH transactions in the last 7 days (README)."""
    fake.btc_transfers = [
        btc_output(1, 0, datetime(2026, 9, 8, 10, 0, tzinfo=UTC), Decimal(1_200), BINANCE),
        btc_output(2, 1, datetime(2026, 9, 9, 8, 30, tzinfo=UTC), Decimal(800), UNKNOWN[0]),
        btc_output(3, 0, datetime(2026, 9, 10, 9, 0, tzinfo=UTC), Decimal(600), "not-an-address"),
    ]
    fake.eth_transfers = [
        eth_tx(1, datetime(2026, 9, 9, 7, 0, tzinfo=UTC), Decimal(6_000), WHALE_ETH, EXCHANGE_ETH),
        # returned by the approximate value filter, below the exact threshold: stored, not listed
        eth_tx(
            2, datetime(2026, 9, 9, 9, 0, tzinfo=UTC), Decimal("4999.5"), WHALE_ETH, EXCHANGE_ETH
        ),
    ]


@dataclass
class WhaleHarness:
    db: AsyncEngine
    wall: WallClock
    ticks: FakeClock
    engine: IngestionEngine
    cm: CoinMetricsFake
    bc: BlockchairFake
    ctx: JobContext

    async def run(self, provider_id: str, metric: str, asset: str) -> list[IngestionResult]:
        return await ingest_source(
            self.ctx, source(provider_id, dataset(metric, asset).dataset_id, asset)
        )

    async def run_source(self, item: WhaleSource, times: int = 1) -> list[IngestionResult]:
        out: list[IngestionResult] = []
        for _ in range(times):
            out.extend(await ingest_source(self.ctx, item))
        return out

    async def load_everything(self) -> None:
        """Seed labels, two rich-list snapshots 7 days apart, full daily history and transfers."""
        await import_labels(self.db, parse_label_csv(TEST_LABELS), NOW - timedelta(hours=6))
        self.bc.btc_snapshot = snapshot_then()
        self.wall.current = SNAPSHOT_THEN
        await self.run(blockchair.PROVIDER_ID, "address_balance", "BTC")
        self.bc.btc_snapshot = snapshot_now()
        self.wall.current = SNAPSHOT_NOW
        await self.run(blockchair.PROVIDER_ID, "address_balance", "BTC")
        self.wall.current = NOW
        transfers(self.bc)
        for item in SOURCES:
            if item.dataset.metric != "address_balance":
                # enough runs to finish every history chunk (Coin Metrics 2, Blockchair ≤ 7)
                await self.run_source(item, times=8 if item.provider_id == "blockchair" else 3)

    async def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.db.connect() as conn:
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]


@pytest.fixture
async def whales(db: AsyncEngine, test_settings: Settings) -> WhaleHarness:
    wall = WallClock(NOW)
    ticks = FakeClock()
    repo = IngestionRepository(db)
    engine = IngestionEngine(repo, FileSystemArchive(test_settings.raw_archive_dir), clock=wall)
    cm, bc = CoinMetricsFake(), BlockchairFake()
    clients = {
        pid: ProviderHttpClient(
            ADAPTERS[pid].capabilities,
            transport=fake.transport(),
            retry=RetryPolicy(max_attempts=2, base_delay=0.5, jitter=0),
            recorder=RepositoryRecorder(repo),
            environ={},
            sleep=ticks.sleep,
            clock=ticks,
        )
        for pid, fake in ((coinmetrics.PROVIDER_ID, cm), (blockchair.PROVIDER_ID, bc))
    }
    for item in SOURCES:
        await engine.register(item.dataset, ADAPTERS[item.provider_id], PRIORITY[item.provider_id])
    ctx = JobContext(engine, db, clients, wall)
    return WhaleHarness(db, wall, ticks, engine, cm, bc, ctx)

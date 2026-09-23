"""Market-data ingestion jobs: latest data and resumable history backfill.

Both run through the Phase 4 :class:`IngestionEngine`, so every run is logged in ``ops.job_run``
with its request log, raw payloads and quality findings.

- ``ingest_latest``: the most recent closed periods for one dataset and provider, for every asset.
  The window reaches back to the newest stored point (bounded), so a worker that was stopped for a
  while catches up instead of leaving an unrecorded hole.
- ``backfill_step``: walks history backwards from the first run, one request-sized chunk at a
  time, recording a checkpoint (``ops.backfill_state``). It stops at the configured depth, or
  when the provider has returned no data for several consecutive chunks (start of the
  instrument's history).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.logging import get_logger
from cfi.core.time import floor_to_period, utc_now
from cfi.db import tables as t
from cfi.domain.datasets import DatasetSpec
from cfi.ingestion.engine import IngestionEngine, IngestionResult
from cfi.market.universe import ASSET_SYMBOLS
from cfi.providers import binance, bybit, coinbase, coingecko, kraken, okx
from cfi.providers.base import FetchWindow, ProviderAdapter
from cfi.providers.http import ProviderHttpClient

log = get_logger(__name__)

# Latest ingestion: how many recent periods each run asks for.
LOOKBACK_PERIODS: dict[str, int] = {"1m": 15, "5m": 12, "15m": 8, "1h": 6, "4h": 6, "1d": 3}
# Catch-up after downtime is bounded to this many periods per run (older holes: backfill/gaps).
MAX_CATCH_UP_PERIODS = 1000
# Default history depth per timeframe (days). Decision C1/B4 pending — configurable.
BACKFILL_DAYS: dict[str, int] = {
    "1m": 7,
    "5m": 30,
    "15m": 90,
    "1h": 730,
    "4h": 1460,
    "1d": 3650,
    "market_cap_1d": 365,  # CoinGecko Demo/public history limit
}
# Bars per backfill request (provider maximum).
CHUNK_BARS: dict[str, int] = {
    coinbase.PROVIDER_ID: coinbase.MAX_CANDLES,
    binance.PROVIDER_ID: binance.MAX_KLINES,
    bybit.PROVIDER_ID: bybit.MAX_KLINES,
    okx.PROVIDER_ID: 10 * okx.PAGE_LIMIT,  # ten 100-bar pages per backfill step
    kraken.PROVIDER_ID: kraken.MAX_ENTRIES,
    coingecko.PROVIDER_ID: coingecko.MAX_DAYS,
}
EMPTY_CHUNKS_TO_STOP = 3


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a job needs: the ingestion engine, a database handle, and one client per provider."""

    engine: IngestionEngine
    db: AsyncEngine
    clients: dict[str, ProviderHttpClient]
    clock: Callable[[], datetime] = utc_now


def subjects_for(adapter: ProviderAdapter, dataset: DatasetSpec) -> list[str | None]:
    """Latest market caps come in one request for all assets; everything else is per asset."""
    if adapter.provider_id == coingecko.PROVIDER_ID and dataset.period == "event":
        return [None]
    return list(ASSET_SYMBOLS)


async def _latest_stored(
    db: AsyncEngine, dataset: DatasetSpec, provider: str, asset: str
) -> datetime | None:
    table = t.market_bar if dataset.kind == "bar" else t.observation
    value_col = table.c.close if dataset.kind == "bar" else table.c.value
    stmt = (
        select(func.max(table.c.event_time))
        .select_from(table.join(t.series, t.series.c.series_id == table.c.series_id))
        .where(
            t.series.c.dataset_id == dataset.dataset_id,
            t.series.c.asset == asset,
            table.c.source_provider == provider,
            value_col.is_not(None),
        )
    )
    async with db.connect() as conn:
        latest: datetime | None = (await conn.execute(stmt)).scalar()
    return latest


async def latest_window(
    ctx: JobContext, dataset: DatasetSpec, provider: str, subject: str | None
) -> FetchWindow:
    now = ctx.clock()
    period = dataset.period_length
    if period is None:  # event series (ticker, latest market cap): one snapshot request
        return FetchWindow(now - timedelta(hours=1), now, subject)
    end = floor_to_period(now, period)  # open time of the current, unfinished bar
    start = end - LOOKBACK_PERIODS.get(dataset.period, 6) * period
    if subject is not None:
        latest = await _latest_stored(ctx.db, dataset, provider, subject)
        if latest is not None and latest + period < start:
            start = max(latest + period, end - MAX_CATCH_UP_PERIODS * period)
    return FetchWindow(start, end, subject)


async def ingest_latest(
    ctx: JobContext, adapter: ProviderAdapter, dataset: DatasetSpec
) -> list[IngestionResult]:
    client = ctx.clients[adapter.provider_id]
    results = []
    for subject in subjects_for(adapter, dataset):
        window = await latest_window(ctx, dataset, adapter.provider_id, subject)
        results.append(await ctx.engine.ingest(dataset, adapter, client, window))
    return results


def backfill_days(dataset: DatasetSpec, overrides: dict[str, int]) -> int:
    key = "market_cap_1d" if dataset.metric == "market_cap" else dataset.period
    return overrides.get(key, BACKFILL_DAYS[key])


async def backfill_step(
    ctx: JobContext,
    adapter: ProviderAdapter,
    dataset: DatasetSpec,
    subject: str,
    *,
    depth_days: int,
) -> IngestionResult | None:
    """Fetch the next older chunk of history. Returns ``None`` when this series is complete."""
    period = dataset.period_length
    if period is None:
        return None
    repo = ctx.engine.repo
    now = ctx.clock()
    state = await repo.backfill_state(dataset.dataset_id, adapter.provider_id, subject)
    if state is None:
        anchor = floor_to_period(now, period)
        state = {
            "covered_from": anchor,
            "covered_to": anchor,
            "target_start": anchor - timedelta(days=depth_days),
            "complete": False,
            "empty_chunks": 0,
        }
    if state["complete"]:
        return None

    end: datetime = state["covered_from"]
    target: datetime = state["target_start"]
    chunk = CHUNK_BARS[adapter.provider_id] * period
    start = max(target, end - chunk)
    if start >= end:
        await _save(ctx, dataset, adapter, subject, state, end, True, 0, "target depth reached")
        return None

    result = await ctx.engine.ingest(
        dataset,
        adapter,
        ctx.clients[adapter.provider_id],
        FetchWindow(start, end, subject),
        job_type="backfill",
    )
    if result.status == "failed":
        # Do not advance: the same chunk is retried on the next run (the failure is logged).
        return result

    empty = 0 if result.earliest_received is not None else state["empty_chunks"] + 1
    complete = start <= target or empty >= EMPTY_CHUNKS_TO_STOP
    if start <= target:
        note = "target depth reached"
    elif empty >= EMPTY_CHUNKS_TO_STOP:
        note = (
            f"no data before {start.isoformat()} in {EMPTY_CHUNKS_TO_STOP} consecutive requests: "
            "start of the provider's available history for this instrument"
        )
    else:
        note = None
    await _save(ctx, dataset, adapter, subject, state, start, complete, empty, note)
    return result


async def _save(
    ctx: JobContext,
    dataset: DatasetSpec,
    adapter: ProviderAdapter,
    subject: str,
    state: dict[str, object],
    covered_from: datetime,
    complete: bool,
    empty: int,
    note: str | None,
) -> None:
    covered_to = state["covered_to"]
    target = state["target_start"]
    if not isinstance(covered_to, datetime) or not isinstance(target, datetime):
        raise TypeError("backfill state timestamps must be datetimes")
    await ctx.engine.repo.save_backfill_state(
        dataset.dataset_id,
        adapter.provider_id,
        subject,
        covered_from=covered_from,
        covered_to=covered_to,
        target_start=target,
        complete=complete,
        empty_chunks=empty,
        note=note,
        now=ctx.clock(),
    )

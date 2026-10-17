"""Phase 51 step 2, database-backed: the five query methods that can be served from a
``pit_revision_window`` return exactly what their production SQL returns, on real PostgreSQL.

Each case seeds revisioned rows (gaps, ``missing`` values, 1-3 revisions per event, hourly
``available_at`` and ``ingested_at`` so request instants land exactly on row boundaries, plus rows
of other series/providers/venues the query must not return), then compares many random requests
answered inside a ``pit_read_scope`` (window path) with the same requests outside a scope (the
unchanged SQL). Needs the integration services and runs only in the ``<name>_test`` database that
``tests/integration/conftest.py`` creates and empties.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.pit_memo import pit_read_scope
from cfi.db import tables as t
from cfi.derivatives.universe import FUNDING_RATE
from cfi.domain.datasets import DatasetSpec
from cfi.ingestion.repository import IngestionRepository
from cfi.macro.queries import MacroQueries
from cfi.macro.universe import VIX
from cfi.market.queries import MarketQueries
from cfi.market.sources import VENUES
from cfi.market.universe import ohlcv_dataset_id
from cfi.market_structure.queries import MarketStructureQueries
from cfi.market_structure.universe import TOTAL_MARKET_CAP_USD
from cfi.retail.queries import RetailQueries
from cfi.retail.universe import SMALL_OUTPUT_COUNT
from tests.integration.conftest import requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

T0 = datetime(2026, 1, 1, tzinfo=UTC)  # far in the past: every request is below the window cutoff
DAY = timedelta(days=1)
Req = tuple[datetime, datetime, datetime, datetime]  # start, end, as_of, knowledge_time
Call = Callable[[Req], Awaitable[list[dict[str, Any]]]]
_COINBASE = VENUES["coinbase"]
_BAR_DATASET = ohlcv_dataset_id(_COINBASE.quote, "1d")


async def _register(market: MarketHarness) -> None:
    await market.register()
    repo = IngestionRepository(market.db)
    for spec in (VIX, TOTAL_MARKET_CAP_USD, SMALL_OUTPUT_COUNT, FUNDING_RATE):
        await repo.sync_dataset(spec, T0)


async def _series(
    db: AsyncEngine, spec: DatasetSpec | None, *, asset: str, ref: str, venue: str | None = None
) -> int:
    async with db.begin() as conn:
        result = await conn.execute(
            insert(t.series)
            .values(
                dataset_id=_BAR_DATASET if spec is None else spec.dataset_id,
                metric="spot_ohlcv" if spec is None else spec.metric,
                asset=asset,
                subject_ref=ref,
                venue=venue,
                period="1d" if spec is None else spec.period,
                unit=_COINBASE.quote if spec is None else spec.unit,
                created_at=T0,
            )
            .returning(t.series.c.series_id)
        )
        return int(result.scalar_one())


def _revisions(
    rng: random.Random, series_id: int, provider: str, *, bars: bool, days: int = 70
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for d in range(days):
        if rng.random() < 0.1:  # gap: no row at all for this event_time
            continue
        event = T0 + DAY * d
        for rev in range(rng.choice([1, 1, 2, 3])):
            available = event + DAY + timedelta(hours=rng.randint(0, 5) + 7 * rev)
            ingested = available + timedelta(minutes=rng.choice([0, 0, 1, 60, 600]))
            missing = (not bars) and rng.random() < 0.05
            value = Decimal(rng.randint(1, 10**6)) / Decimal(100)
            row: dict[str, Any] = {
                "series_id": series_id,
                "event_time": event,
                "available_at": available,
                "available_at_estimated": False,
                "ingested_at": ingested,
                "source_provider": provider,
                "original_source": "test-fixture",
                "raw_ref": None,
                "revision": rev,
                "pit_reliability": "native",
                "quality_status": "missing" if missing else "ok",
                "quality_note": "gap" if missing else None,
                "confidence": None,
                "transformations": ["test"] if rev else [],
            }
            if bars:
                row.update(
                    open=value,
                    high=value + 1,
                    low=value - 1,
                    close=value,
                    volume_base=Decimal(1000),
                    volume_quote=value * 1000,
                    trade_count=10,
                )
            else:
                row["value"] = None if missing else value
            rows.append(row)
    return rows


async def _insert(db: AsyncEngine, table: Any, rows: list[dict[str, Any]]) -> None:
    async with db.begin() as conn:
        await conn.execute(insert(table), rows)


def _requests(rng: random.Random, n: int = 40) -> list[Req]:
    out: list[Req] = []
    for _ in range(n):
        as_of = T0 + timedelta(hours=rng.randint(24, 24 * 72))
        knowledge_time = as_of + timedelta(minutes=rng.choice([-600, -60, -1, 0, 0, 1, 60]))
        start = T0 + DAY * rng.randint(0, 60)
        out.append((start, start + DAY * rng.randint(1, 40), as_of, knowledge_time))
    return out


async def _seed_bars(db: AsyncEngine, rng: random.Random) -> Call:
    mine = await _series(db, None, asset="BTC", ref=_COINBASE.instruments["BTC"], venue="coinbase")
    other = await _series(db, None, asset="ETH", ref=_COINBASE.instruments["ETH"], venue="coinbase")
    rows = _revisions(rng, mine, _COINBASE.provider_id, bars=True)
    rows += _revisions(rng, mine, "some-other-provider", bars=True)  # same series, other provider
    rows += _revisions(rng, other, _COINBASE.provider_id, bars=True)  # other series
    await _insert(db, t.market_bar, rows)
    q = MarketQueries(db)
    return lambda r: q.bars(mine, _COINBASE.provider_id, r[0], r[1], r[2])


async def _seed_observations(
    db: AsyncEngine, rng: random.Random, spec: DatasetSpec, *, venue: str | None
) -> tuple[int, int]:
    mine = await _series(db, spec, asset="TSUBJ", ref="TSUBJ", venue=venue)
    other = await _series(db, spec, asset="OTHER", ref="OTHER", venue=venue)
    rows = _revisions(rng, mine, "p1", bars=False)
    rows += _revisions(rng, other, "p1", bars=False)
    if venue is not None:  # same asset on another venue: only the venue-filtered query ignores it
        other_venue = await _series(db, spec, asset="TSUBJ", ref="TSUBJ-v", venue="elsewhere")
        rows += _revisions(rng, other_venue, "p1", bars=False)
    await _insert(db, t.observation, rows)
    return mine, other


async def _seed_macro(db: AsyncEngine, rng: random.Random) -> Call:
    await _seed_observations(db, rng, VIX, venue=None)
    q = MacroQueries(db)
    return lambda r: q.observations(
        VIX.dataset_id, subject="TSUBJ", start=r[0], end=r[1], as_of=r[2], knowledge_time=r[3]
    )


async def _seed_market_structure(db: AsyncEngine, rng: random.Random) -> Call:
    await _seed_observations(db, rng, TOTAL_MARKET_CAP_USD, venue=None)
    q = MarketStructureQueries(db)
    return lambda r: q.observations(
        TOTAL_MARKET_CAP_USD.dataset_id,
        subject="TSUBJ",
        start=r[0],
        end=r[1],
        as_of=r[2],
        knowledge_time=r[3],
    )


async def _seed_retail(db: AsyncEngine, rng: random.Random) -> Call:
    await _seed_observations(db, rng, SMALL_OUTPUT_COUNT, venue=None)
    q = RetailQueries(db)
    return lambda r: q.observations(
        SMALL_OUTPUT_COUNT.dataset_id,
        subject="TSUBJ",
        start=r[0],
        end=r[1],
        as_of=r[2],
        knowledge_time=r[3],
    )


async def _seed_retail_derivatives(db: AsyncEngine, rng: random.Random) -> Call:
    await _seed_observations(db, rng, FUNDING_RATE, venue="binance")
    q = RetailQueries(db)
    return lambda r: q.derivatives_observations(
        FUNDING_RATE.dataset_id,
        asset="TSUBJ",
        start=r[0],
        end=r[1],
        as_of=r[2],
        knowledge_time=r[3],
    )


SEEDERS: dict[str, Callable[[AsyncEngine, random.Random], Awaitable[Call]]] = {
    "market.bars": _seed_bars,
    "macro.observations": _seed_macro,
    "market_structure.observations": _seed_market_structure,
    "retail.observations": _seed_retail,
    "retail.derivatives_observations": _seed_retail_derivatives,
}


@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("name", list(SEEDERS))
async def test_window_results_equal_the_production_sql(
    market: MarketHarness, name: str, seed: int
) -> None:
    await _register(market)
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture data
    call = await SEEDERS[name](market.db, rng)
    requests = _requests(rng)

    direct = [await call(r) for r in requests]  # no scope: the unchanged SQL
    assert any(direct)  # not vacuous
    with pit_read_scope() as stats:
        windowed = [await call(r) for r in requests]

    assert windowed == direct
    # one series per query and no ties, so every request is served from the window
    assert stats.window_hits == len(requests)
    assert stats.window_fallbacks == 0
    assert stats.window_loads < len(requests)  # the loaded ranges really were reused


async def test_a_visible_revision_tie_between_series_falls_back_to_the_sql(
    market: MarketHarness,
) -> None:
    await _register(market)
    a = await _series(market.db, VIX, asset="TSUBJ", ref="TSUBJ-a")
    b = await _series(market.db, VIX, asset="TSUBJ", ref="TSUBJ-b")
    event = T0 + DAY * 3
    base = {
        "event_time": event,
        "available_at": event + DAY,
        "available_at_estimated": False,
        "ingested_at": event + DAY,
        "source_provider": "p1",
        "original_source": "test-fixture",
        "raw_ref": None,
        "revision": 0,
        "pit_reliability": "native",
        "quality_status": "ok",
        "quality_note": None,
        "confidence": None,
        "transformations": [],
    }
    await _insert(
        market.db,
        t.observation,
        [
            {**base, "series_id": a, "value": Decimal(1)},
            {**base, "series_id": b, "value": Decimal(2)},
        ],
    )
    q = MacroQueries(market.db)
    when = event + DAY * 2

    async def read() -> list[dict[str, Any]]:
        return await q.observations(
            VIX.dataset_id,
            subject="TSUBJ",
            start=T0,
            end=T0 + DAY * 10,
            as_of=when,
            knowledge_time=when,
        )

    direct = await read()
    with pit_read_scope() as stats:
        windowed = await read()
    assert len(direct) == 1
    assert windowed == direct  # whichever row PostgreSQL picks, the answer is PostgreSQL's
    assert stats.window_fallbacks == 1
    assert stats.window_hits == 0


async def test_a_row_stored_after_the_window_was_loaded_is_invisible_exactly_as_in_sql(
    market: MarketHarness,
) -> None:
    await _register(market)
    rng = random.Random(7)  # noqa: S311 - deterministic fixture data
    series_id = await _series(market.db, VIX, asset="TSUBJ", ref="TSUBJ")
    await _insert(market.db, t.observation, _revisions(rng, series_id, "p1", bars=False))
    q = MacroQueries(market.db)
    when = T0 + DAY * 40

    async def read(at: datetime) -> list[dict[str, Any]]:
        return await q.observations(
            VIX.dataset_id,
            subject="TSUBJ",
            start=T0,
            end=T0 + DAY * 30,
            as_of=at,
            knowledge_time=at,
        )

    with pit_read_scope() as stats:
        before = await read(when)  # creates the window
        late = datetime.now(UTC)  # stored now: ingested_at is after the window's cutoff
        await _insert(
            market.db,
            t.observation,
            [
                {
                    "series_id": series_id,
                    "event_time": T0 + DAY * 3,
                    "available_at": T0 + DAY * 3,
                    "available_at_estimated": False,
                    "ingested_at": late,
                    "value": Decimal(999),
                    "source_provider": "p1",
                    "original_source": "test-fixture",
                    "raw_ref": None,
                    "revision": 99,
                    "pit_reliability": "native",
                    "quality_status": "ok",
                    "quality_note": None,
                    "confidence": None,
                    "transformations": [],
                }
            ],
        )
        after = await read(when)  # historical request: window path
        current = await read(late + timedelta(hours=1))  # beyond the cutoff: SQL path
    assert stats.window_hits == 2  # `before` and `after`
    assert stats.window_fallbacks == 1  # `current`, beyond the cutoff
    assert after == before == await read(when)  # outside the scope: SQL, row still invisible
    assert any(r["revision"] == 99 for r in current)  # the SQL path does see it at a later time
    assert current == await read(late + timedelta(hours=1))

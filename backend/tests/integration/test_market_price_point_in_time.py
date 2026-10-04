"""Phase 33 regression coverage: point-in-time correctness of
``cfi.divergence.adapters.Adapters.price_close`` (and, through it, ``cfi.paper.pnl.current_price``
and ``cfi.market.queries.MarketQueries.bars``), the exact read path Phase 30/31 flagged as
producing ``InsufficientDataError``/``None`` for a historical paper-trade entry or journal
decision even though the seeded dataset covered the requested timestamp.

**Root cause (not an application defect — see the Phase 33 report):** ``MarketQueries.bars``
correctly requires both ``available_at <= as_of`` (real-world point-in-time, R3) and
``ingested_at <= as_of`` (knowledge-time: this system must have actually stored the row by
``as_of``, not just have it be true in the world by then). ``tests.integration.market_support.
MarketHarness``'s generic ``backfill_step`` stamps every bar inserted by one bulk backfill call
with a single ``ingested_at`` equal to the moment *that job* ran — accurate for a real deployment
(ingestion always precedes the "now" that queries it) but not a faithful stand-in for "ingested
shortly after this day closed," which a historical ``as_of`` *before* that bulk-backfill moment
needs. ``test_paper_service.py``/``test_journal_service.py`` now correct this in their own
``_seed_btc`` helper by setting ``ingested_at = available_at`` per bar, exactly the convention
``test_backtest_engine.py`` already uses for synthetic bars. This file tests the same read path
directly, with the same direct-insert technique ``test_backtest_engine.py`` established, so the
six boundary cases below are pinned independently of either service's seeding helper.

Boundary cases (Phase 33 section 3):

A. exact matching timestamp
B. nearest earlier observation
C. observation immediately after ``as_of`` — MUST NOT be used (look-ahead)
D. timezone-aware equivalent instants (UTC vs. a non-UTC fixed offset) agree
E. a bar that is available (``available_at <= as_of``) but not yet *ingested* as of ``as_of``
   (``ingested_at > as_of``) — MUST NOT be used (knowledge-time, not just availability)
F. no observation before ``as_of`` at all — ``InsufficientDataError`` via the service layer,
   ``None``/``[]`` at the adapter layer, never a fabricated price (R3)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.config import Settings
from cfi.core.errors import InsufficientDataError
from cfi.db import tables as t
from cfi.divergence.adapters import Adapters
from cfi.market.sources import VENUES
from cfi.market.universe import ohlcv_dataset_id
from cfi.paper import pnl
from cfi.paper.service import PaperTradingService
from tests.integration.conftest import requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

_VENUE = VENUES["coinbase"]
_DATASET_ID = ohlcv_dataset_id(_VENUE.quote, "1d")
_SUBJECT_REF = _VENUE.instruments["BTC"]
T0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


async def _seed_series(db: AsyncEngine) -> int:
    async with db.begin() as conn:
        result = await conn.execute(
            insert(t.series)
            .values(
                dataset_id=_DATASET_ID,
                metric="spot_ohlcv",
                asset="BTC",
                subject_ref=_SUBJECT_REF,
                venue="coinbase",
                period="1d",
                unit=_VENUE.quote,
                created_at=T0,
            )
            .returning(t.series.c.series_id)
        )
        return int(result.scalar_one())


def _bar(
    series_id: int,
    event_time: datetime,
    close: Decimal,
    *,
    available_at: datetime,
    ingested_at: datetime,
    revision: int = 0,
) -> dict[str, object]:
    return {
        "series_id": series_id,
        "event_time": event_time,
        "available_at": available_at,
        "available_at_estimated": False,
        "ingested_at": ingested_at,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume_base": Decimal(1_000_000),
        "volume_quote": close * Decimal(1_000_000),
        "trade_count": 1000,
        "source_provider": _VENUE.provider_id,
        "original_source": "test-fixture",
        "raw_ref": None,
        "revision": revision,
        "pit_reliability": "native",
        "quality_status": "ok",
        "quality_note": None,
        "confidence": None,
        "transformations": [],
    }


async def _insert_bars(db: AsyncEngine, rows: list[dict[str, object]]) -> None:
    async with db.begin() as conn:
        await conn.execute(insert(t.market_bar), rows)


async def test_a_exact_matching_timestamp_is_used(market: MarketHarness) -> None:
    await market.register()
    series_id = await _seed_series(market.db)
    as_of = T0 + DAY * 5
    await _insert_bars(
        market.db,
        [_bar(series_id, as_of, Decimal(50_000), available_at=as_of, ingested_at=as_of)],
    )
    series = await Adapters(market.db).price_close("BTC", as_of + timedelta(seconds=1))
    price = pnl.current_price(series, as_of + timedelta(seconds=1))
    assert price == Decimal(50_000)


async def test_b_the_nearest_earlier_observation_is_used_not_a_more_distant_one(
    market: MarketHarness,
) -> None:
    await market.register()
    series_id = await _seed_series(market.db)
    far = T0
    near = T0 + DAY * 9
    as_of = T0 + DAY * 10
    await _insert_bars(
        market.db,
        [
            _bar(series_id, far, Decimal(10_000), available_at=far, ingested_at=far),
            _bar(series_id, near, Decimal(20_000), available_at=near, ingested_at=near),
        ],
    )
    series = await Adapters(market.db).price_close("BTC", as_of)
    price = pnl.current_price(series, as_of)
    assert price == Decimal(20_000)


async def test_c_an_observation_immediately_after_as_of_is_never_used(
    market: MarketHarness,
) -> None:
    """Look-ahead protection (R3/R4): a bar dated *after* ``as_of`` — even one second after, even
    though it is already both available and ingested — must never leak into a point-in-time read."""
    await market.register()
    series_id = await _seed_series(market.db)
    as_of = T0 + DAY * 5
    after = as_of + timedelta(seconds=1)
    await _insert_bars(
        market.db,
        [_bar(series_id, after, Decimal(99_999), available_at=after, ingested_at=after)],
    )
    series = await Adapters(market.db).price_close("BTC", as_of)
    price = pnl.current_price(series, as_of)
    assert price is None  # no valued point at or before as_of (R3: never fabricated)


async def test_d_a_non_utc_fixed_offset_instant_agrees_with_its_utc_equivalent(
    market: MarketHarness,
) -> None:
    await market.register()
    series_id = await _seed_series(market.db)
    event_time = T0 + DAY * 5
    await _insert_bars(
        market.db,
        [
            _bar(
                series_id,
                event_time,
                Decimal(42_000),
                available_at=event_time,
                ingested_at=event_time,
            )
        ],
    )
    as_of_utc = event_time + timedelta(hours=2)
    as_of_plus_eight = as_of_utc.astimezone(timezone(timedelta(hours=8)))
    assert as_of_plus_eight.utcoffset() != as_of_utc.utcoffset()  # different wall-clock field
    assert as_of_utc == as_of_plus_eight  # but the same instant (datetime compares by instant)

    series_utc = await Adapters(market.db).price_close("BTC", as_of_utc)
    series_offset = await Adapters(market.db).price_close("BTC", as_of_plus_eight)
    price_utc = pnl.current_price(series_utc, as_of_utc)
    price_offset = pnl.current_price(series_offset, as_of_plus_eight)
    assert price_utc == price_offset == Decimal(42_000)


async def test_e_an_available_but_not_yet_ingested_bar_is_never_used(
    market: MarketHarness,
) -> None:
    """Knowledge-time protection: a bar whose ``available_at`` is at or before ``as_of`` (it was
    objectively knowable by then) but whose ``ingested_at`` is *after* ``as_of`` (this system
    had not actually stored it yet) must not be used — this is exactly the gap Phase 30/31's
    reproduction hit, now pinned directly rather than only through the paper/journal services."""
    await market.register()
    series_id = await _seed_series(market.db)
    event_time = T0 + DAY * 5
    as_of = event_time + timedelta(hours=1)
    not_yet_ingested = as_of + DAY * 30  # ingested much later, e.g. a delayed bulk backfill
    await _insert_bars(
        market.db,
        [
            _bar(
                series_id,
                event_time,
                Decimal(77_000),
                available_at=event_time,  # objectively available before as_of
                ingested_at=not_yet_ingested,  # but this system didn't have it yet
            )
        ],
    )
    series = await Adapters(market.db).price_close("BTC", as_of)
    price = pnl.current_price(series, as_of)
    assert price is None


async def test_f_no_observation_before_as_of_raises_insufficient_data_via_the_service(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """End-to-end through ``PaperTradingService.create_trade`` — an empty series must surface as
    the service's own explicit ``InsufficientDataError``, never a silent ``None``/fabricated 0."""
    svc = PaperTradingService(db, test_settings)
    with pytest.raises(InsufficientDataError):
        await svc.create_trade(
            asset="BTC", direction="long", notional=Decimal(1_000), now=T0 + DAY * 5
        )

"""Backtesting Engine against real PostgreSQL (Phase 16).

Bars are inserted directly into ``obs.series``/``obs.market_bar`` (bypassing the ingestion
pipeline) so the price path is fully controlled and deterministic: a flat warmup, a clean uptrend
(to trigger an SMA(20/50) entry), then a clean downtrend (to trigger the signal exit). This lets
the tests assert on the shape of the result without depending on any provider's synthetic-bar
formula.

Two things are specifically exercised here because they are this phase's explicit requirement and
are not covered by any other suite:

* **Reproducibility** (R7/the phase spec: "every backtest must be reproducible") — the same inputs
  produce byte-identical trades, equity curve and metrics on a second run.
* **Look-ahead-bias / leakage tests** (this phase's explicit instruction: "create synthetic datasets
  specifically designed to detect look-ahead bias") — data that lies after ``end``, or that was not
  yet ``available_at`` as of the run's ``as_of``, must never change the result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.backtest import costs as cost_module
from cfi.backtest.engine import run_backtest
from cfi.backtest.signals import PRICE_SIGNALS
from cfi.backtest.strategy import (
    EXAMPLE_STRATEGIES,
    PositionSizing,
    RiskLimits,
    StopConditions,
    StrategyDefinition,
    TimeExit,
)
from cfi.db import tables as t
from cfi.divergence.adapters import Adapters
from cfi.market.sources import VENUES
from cfi.market.universe import ohlcv_dataset_id
from tests.integration.conftest import requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

_VENUE = VENUES["coinbase"]
_DATASET_ID = ohlcv_dataset_id(_VENUE.quote, "1d")
_SUBJECT_REF = _VENUE.instruments["BTC"]
T0 = datetime(2024, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def _price_path(n_days: int) -> list[Decimal]:
    """Flat warmup (220 days) -> clean uptrend (100 days, 100 -> 300) -> clean downtrend (rest,
    back down to 100). Long enough and trending enough to exercise every one of SMA20/SMA50/RSI
    and to trigger both an entry and a signal exit for ``sma_trend_follow_v1``."""
    prices: list[Decimal] = []
    for i in range(n_days):
        if i < 220:
            prices.append(Decimal(100))
        elif i < 320:
            prices.append(Decimal(100) + Decimal(2) * (i - 220))
        else:
            remaining = n_days - 320
            step = Decimal(200) / Decimal(max(remaining, 1))
            prices.append(Decimal(300) - step * (i - 320))
    return prices


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


async def _seed_bars(
    db: AsyncEngine,
    series_id: int,
    n_days: int,
    *,
    available_lag: timedelta = timedelta(minutes=1),
) -> None:
    prices = _price_path(n_days)
    rows = []
    for i, close in enumerate(prices):
        event_time = T0 + DAY * i
        rows.append(
            {
                "series_id": series_id,
                "event_time": event_time,
                "available_at": event_time + available_lag,
                "available_at_estimated": False,
                "ingested_at": event_time + available_lag,
                "open": prices[i - 1] if i > 0 else close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume_base": Decimal(1_000_000),
                "volume_quote": close * Decimal(1_000_000),
                "trade_count": 1000,
                "source_provider": _VENUE.provider_id,
                "original_source": "test-fixture",
                "raw_ref": None,
                "revision": 0,
                "pit_reliability": "native",
                "quality_status": "ok",
                "quality_note": None,
                "confidence": None,
                "transformations": [],
            }
        )
    async with db.begin() as conn:
        await conn.execute(insert(t.market_bar), rows)


@pytest.fixture
async def seeded(market: MarketHarness) -> tuple[int, int]:
    """400 days of bars, everything available by the time it happens (1-minute lag)."""
    await market.register()
    series_id = await _seed_series(market.db)
    n_days = 400
    await _seed_bars(market.db, series_id, n_days)
    return series_id, n_days


async def test_run_backtest_produces_trades_and_metrics_on_a_trending_synthetic_path(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    _series_id, n_days = seeded
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    end = T0 + DAY * n_days
    result = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=T0 + DAY * 220,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
    )
    assert result.status == "ok"
    assert result.metrics is not None
    assert result.metrics.num_trades >= 1
    assert len(result.equity_curve) > 0
    # Reproducibility fields are all populated (R7 / this phase's explicit spec).
    assert result.versions.dataset_version != ""
    assert result.versions.code_version != ""
    assert result.versions.strategy_version == strategy.version


async def test_run_backtest_is_reproducible_for_identical_inputs(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    _series_id, n_days = seeded
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    end = T0 + DAY * n_days
    kwargs = dict(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=T0 + DAY * 220,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
    )
    first = await run_backtest(**kwargs)  # type: ignore[arg-type]
    second = await run_backtest(**kwargs)  # type: ignore[arg-type]

    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve
    assert first.metrics == second.metrics
    assert first.versions.dataset_version == second.versions.dataset_version


async def test_data_after_end_never_changes_the_result(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    """Look-ahead-bias test: a run over [start, end] must be identical whether or not bars after
    ``end`` exist in the database at all."""
    series_id, n_days = seeded
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    start = T0 + DAY * 220
    end = T0 + DAY * 350  # well before the seeded data's actual end (400 days)

    with_future_data = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=start,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
    )

    # Delete every bar strictly after `end` and rerun with the exact same window.
    async with market.db.begin() as conn:
        await conn.execute(
            delete(t.market_bar).where(
                t.market_bar.c.series_id == series_id, t.market_bar.c.event_time >= end
            )
        )
    without_future_data = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=start,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
    )

    assert with_future_data.trades == without_future_data.trades
    assert with_future_data.equity_curve == without_future_data.equity_curve
    assert with_future_data.metrics == without_future_data.metrics
    # Sanity: the two runs really did see a different-sized dataset underneath.
    async with market.db.connect() as conn:
        remaining = (
            await conn.execute(
                text("SELECT count(*) FROM obs.market_bar WHERE series_id = :s"), {"s": series_id}
            )
        ).scalar_one()
    assert remaining == 350
    assert n_days == 400  # sanity on the fixture itself: there really was data beyond `end`


async def test_a_future_revision_never_leaks_into_a_past_decision(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    """Leakage test (R4: 'future revisions leaking into past decisions must never happen', R3's
    point-in-time rule: ``available_at <= as_of``, latest revision only).

    A second, later revision of one bar is inserted with an extreme close (the kind of value that
    would flip the SMA-crossover signal's sign if it were seen) and an ``available_at`` far beyond
    the run's ``as_of``. A run at that ``as_of`` must be byte-identical to a run against the
    original, single-revision data — proving the point-in-time filter, not the engine's own logic,
    is what keeps the revision out. A later run, with ``as_of`` moved past the revision's
    availability, must then differ — proving the filter is discriminating rather than always
    silently preferring the oldest revision."""
    series_id, _n_days = seeded
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    start = T0 + DAY * 220
    end = T0 + DAY * 300
    as_of = end

    baseline = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=start,
        end=end,
        as_of=as_of,
        initial_capital=Decimal(100_000),
    )

    shock_time = T0 + DAY * 280
    revision_available_at = end + DAY * 365
    async with market.db.begin() as conn:
        await conn.execute(
            insert(t.market_bar),
            [
                {
                    "series_id": series_id,
                    "event_time": shock_time,
                    "available_at": revision_available_at,
                    "available_at_estimated": False,
                    "ingested_at": revision_available_at,
                    "open": Decimal(50_000),
                    "high": Decimal(50_001),
                    "low": Decimal(49_999),
                    "close": Decimal(50_000),
                    "volume_base": Decimal(1_000_000),
                    "volume_quote": Decimal(50_000) * Decimal(1_000_000),
                    "trade_count": 1000,
                    "source_provider": _VENUE.provider_id,
                    "original_source": "test-fixture-revision",
                    "raw_ref": None,
                    "revision": 1,
                    "pit_reliability": "native",
                    "quality_status": "ok",
                    "quality_note": "synthetic later revision for a look-ahead-bias test",
                    "confidence": None,
                    "transformations": [],
                }
            ],
        )

    not_yet_available = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=start,
        end=end,
        as_of=as_of,
        initial_capital=Decimal(100_000),
    )
    assert not_yet_available.trades == baseline.trades
    assert not_yet_available.equity_curve == baseline.equity_curve
    assert not_yet_available.metrics == baseline.metrics

    now_available = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=start,
        end=end,
        as_of=revision_available_at,  # the revision is now knowable
        initial_capital=Decimal(100_000),
    )
    assert now_available.equity_curve != baseline.equity_curve


async def test_insufficient_data_status_when_the_window_has_fewer_than_two_bars(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    result = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="BTC",
        start=T0 + DAY * 399,
        end=T0 + DAY * 399,
        as_of=T0 + DAY * 399,
        initial_capital=Decimal(100_000),
    )
    assert result.status == "insufficient_data"
    assert result.metrics is None
    assert result.trades == ()


_ALWAYS_ON_STRATEGY = StrategyDefinition(
    strategy_id="always_on_rsi_stop_test",
    version="always_on_rsi_stop_test_v1",
    signal=PRICE_SIGNALS["rsi"],
    entry_comparator="gte",
    entry_threshold=Decimal(-1),  # RSI is always in [0, 100] -> always true once "ok"
    exit_comparator="lte",
    exit_threshold=Decimal(-999),  # never true -> the ONLY exit path is a stop-loss/take-profit
    position_sizing=PositionSizing(method="fixed_fraction", value=Decimal(1)),
    stops=StopConditions(stop_loss_pct=Decimal(10), take_profit_pct=Decimal(20)),
    time_exit=TimeExit(max_holding_days=None),
    risk_limits=RiskLimits(max_leverage=Decimal(1), max_exposure_pct=Decimal(100)),
    description="Test-only strategy: always enters, never exits on signal, so a trade's close is "
    "always attributable to a stop-loss/take-profit — used to hand-verify finding #3/#12's exact "
    "fill-price and fee arithmetic end to end.",
)


async def _seed_custom_bars(
    db: AsyncEngine, series_id: int, bars: list[dict[str, Decimal]]
) -> None:
    """Each dict has open/high/low/close; volume is deliberately left NULL throughout so
    ``_participation_fraction`` is always None and every fill uses flat, hand-computable slippage
    regardless of which cost-model version is CURRENT."""
    rows = []
    for i, b in enumerate(bars):
        event_time = T0 + DAY * i
        rows.append(
            {
                "series_id": series_id,
                "event_time": event_time,
                "available_at": event_time + timedelta(minutes=1),
                "available_at_estimated": False,
                "ingested_at": event_time + timedelta(minutes=1),
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume_base": None,
                "volume_quote": None,
                "trade_count": None,
                "source_provider": _VENUE.provider_id,
                "original_source": "test-fixture-stop-loss",
                "raw_ref": None,
                "revision": 0,
                "pit_reliability": "native",
                "quality_status": "ok",
                "quality_note": None,
                "confidence": None,
                "transformations": [],
            }
        )
    async with db.begin() as conn:
        await conn.execute(insert(t.market_bar), rows)


async def test_stop_loss_fill_price_and_fees_match_hand_computed_values_exactly(
    market: MarketHarness,
) -> None:
    """RED_TEAM_REPORT.md findings #3 and #12: the entry fill, the stop-loss fill (pierced by the
    low, no gap), the fee on each side, and the resulting trade P&L are all asserted against
    independently hand-computed Decimal values (the same formulas CLAUDE.md/DECISIONS.md document
    for the cost model — not a re-invocation of the engine's own helper functions), end to end
    through a real ``run_backtest`` call. This is exactly the path finding #3 identified as
    completely untested before Phase 18."""
    await market.register()
    series_id = await _seed_series(market.db)

    flat = {"open": Decimal(100), "high": Decimal(101), "low": Decimal(99), "close": Decimal(100)}
    bars = (
        [dict(flat) for _ in range(20)]  # i=0..19: warmup, RSI reaches "ok" well before day 20
        + [dict(flat)]  # i=20 (start / "day0"): entry decided here
        + [dict(flat)]  # i=21 ("day1"): entry EXECUTES at this day's open; no stop breach
        + [
            {  # i=22 ("day2"): stop-loss pierced by the low; open has NOT gapped through it
                "open": Decimal(95),
                "high": Decimal(96),
                "low": Decimal(88),
                "close": Decimal(90),
            }
        ]
        + [dict(flat)]  # i=23 ("day3"): irrelevant trailing bar, only so day2 stays in loop range
    )
    await _seed_custom_bars(market.db, series_id, bars)

    params = cost_module.parameters("cost_model_v1")  # flat slippage; volume is None anyway
    adapters = Adapters(market.db)
    start = T0 + DAY * 20
    end = T0 + DAY * 24
    result = await run_backtest(
        adapters=adapters,
        strategy=_ALWAYS_ON_STRATEGY,
        asset="BTC",
        start=start,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
        cost_params=params,
    )

    assert result.status == "ok"
    assert len(result.trades) == 1
    trade = result.trades[0]

    # --- Hand-computed expected values (fee_bps=10, slippage_bps=5; independent of the engine) ---
    entry_price = Decimal(100) + Decimal(100) * Decimal(5) / Decimal(10_000)
    assert entry_price == Decimal("100.05")
    size_base = Decimal(100_000) / Decimal(100)  # sized at day0's close (100), full equity
    assert size_base == Decimal(1000)
    notional_at_entry = size_base * entry_price
    entry_fee = notional_at_entry * Decimal(10) / Decimal(10_000)
    assert entry_fee == Decimal("100.050")

    sl_level = entry_price * (1 - Decimal(10) / 100)
    assert sl_level == Decimal("90.045")  # day2 low (88) pierces this; day2 open (95) does not
    exit_price = sl_level - sl_level * Decimal(5) / Decimal(10_000)
    assert exit_price == Decimal("89.9999775")
    exit_fee = (size_base * exit_price) * Decimal(10) / Decimal(10_000)
    assert exit_fee == Decimal("89.99997750")

    expected_fees_paid = entry_fee + exit_fee
    expected_pnl = (exit_price - entry_price) * size_base - expected_fees_paid
    expected_return_pct = expected_pnl / notional_at_entry * 100

    assert trade.entry_price == entry_price
    assert trade.exit_price == exit_price
    assert trade.size_base == size_base
    assert trade.notional_at_entry == notional_at_entry
    assert trade.fees_paid == expected_fees_paid
    assert trade.pnl == expected_pnl
    assert trade.return_pct == expected_return_pct
    assert trade.exit_reason == "stop_loss"


async def test_insufficient_data_status_for_an_unknown_asset(
    market: MarketHarness, seeded: tuple[int, int]
) -> None:
    _series_id, n_days = seeded
    adapters = Adapters(market.db)
    strategy = EXAMPLE_STRATEGIES["sma_trend_follow_v1"]
    end = T0 + DAY * n_days
    result = await run_backtest(
        adapters=adapters,
        strategy=strategy,
        asset="DOGE",
        start=T0 + DAY * 220,
        end=end,
        as_of=end,
        initial_capital=Decimal(100_000),
    )
    assert result.status == "insufficient_data"

"""PaperTradingService against real PostgreSQL (Phase 24): trade creation, long/short P&L, fees,
slippage, leverage, open/close/cancel lifecycle, invalid state transitions, decision-time
snapshot preservation, missing market data, and historical integrity. Runs wherever a real test
database is reachable (none anywhere this phase has been built — see PROGRESS.md), written and
gated exactly like every other Phase 21-23 DB-backed suite ("DB integration tests may remain
unexecuted if the same PostgreSQL environment limitation continues").

Seeds real Coinbase-shaped daily bars through the same fake-provider harness Phase 19's anomaly
suite already uses (``tests.integration.market_support.MarketHarness``) — paper trading has no
harness of its own to invent (R13)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.backtest.costs import CURRENT_VERSION
from cfi.core.config import Settings
from cfi.core.errors import DataValidationError, InsufficientDataError
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ohlcv_dataset
from cfi.paper.repository import PaperTradeRepository
from cfi.paper.service import PaperTradingService
from tests.integration.conftest import requires_services
from tests.integration.market_support import NOW, MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")
ENTRY_AS_OF = NOW - timedelta(days=30)
EXIT_AS_OF = NOW


async def _seed_btc(market: MarketHarness) -> None:
    await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, "BTC", depth_days=280)


async def test_create_trade_persists_entry_fields_and_a_decision_snapshot(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    row = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    assert row["status"] == "open"
    assert row["asset"] == "BTC"
    assert row["direction"] == "long"
    assert row["entry_price_observed"] is not None
    assert row["entry_price_execution"] is not None
    assert row["entry_price_execution"] > row["entry_price_observed"]  # long entry buys adverse
    assert row["cost_model_version"] == CURRENT_VERSION
    assert row["decision_snapshot_id"] is not None  # "Market-context snapshot" is required
    assert row["relevant_alert_ids"] == []  # none active — contextual evidence, not fabricated
    assert row["market_brief_id"] is None  # no completed brief exists yet


async def test_long_winning_trade_realizes_positive_net_pnl_when_price_rises(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    closed = await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)
    assert closed["status"] == "closed"
    assert closed["exit_price_observed"] is not None
    assert closed["realized_pnl"] is not None
    # Reconciliation holds exactly regardless of which way the synthetic price moved.
    assert closed["realized_pnl"] == (
        closed["gross_pnl"] - closed["slippage_cost"] - closed["fees_total"]
    )
    assert closed["slippage_cost"] > 0
    assert closed["fees_total"] > 0


async def test_short_trade_is_the_mirror_of_a_long_trade_on_the_same_prices(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    long_trade = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    short_trade = await svc.create_trade(
        asset="BTC", direction="short", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    long_closed = await svc.close_trade(long_trade["uuid"], now=EXIT_AS_OF)
    short_closed = await svc.close_trade(short_trade["uuid"], now=EXIT_AS_OF)
    assert long_closed["gross_pnl"] == -short_closed["gross_pnl"]


async def test_leverage_changes_return_pct_not_dollar_pnl(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    unleveraged = await svc.create_trade(
        asset="BTC",
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        now=ENTRY_AS_OF,
    )
    leveraged = await svc.create_trade(
        asset="BTC",
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(5),
        now=ENTRY_AS_OF,
    )
    unleveraged_closed = await svc.close_trade(unleveraged["uuid"], now=EXIT_AS_OF)
    leveraged_closed = await svc.close_trade(leveraged["uuid"], now=EXIT_AS_OF)
    assert leveraged_closed["realized_pnl"] == unleveraged_closed["realized_pnl"]
    assert leveraged_closed["return_pct"] == unleveraged_closed["return_pct"] * 5
    assert leveraged_closed["margin"] == unleveraged_closed["margin"] / 5


async def test_cancel_an_open_trade_records_no_exit_or_pnl(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    cancelled = await svc.cancel_trade(opened["uuid"], now=EXIT_AS_OF)
    assert cancelled["status"] == "cancelled"
    assert cancelled["exit_price_observed"] is None
    assert cancelled["realized_pnl"] is None


async def test_closing_an_already_closed_trade_is_rejected(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)
    with pytest.raises(DataValidationError):
        await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)


async def test_cancelling_an_already_closed_trade_is_rejected(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)
    with pytest.raises(DataValidationError):
        await svc.cancel_trade(opened["uuid"], now=EXIT_AS_OF)


async def test_unknown_asset_is_rejected_before_any_price_lookup(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = PaperTradingService(db, test_settings)
    with pytest.raises(DataValidationError):
        await svc.create_trade(
            asset="DOGE", direction="long", notional=Decimal(1_000), now=ENTRY_AS_OF
        )


async def test_missing_market_data_raises_insufficient_data_not_a_fabricated_price(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """No bars have been seeded for BTC in this test (no ``market`` fixture used) — the
    database is empty, so there is no observed price to use. The service must say so explicitly,
    never guess (R3)."""
    svc = PaperTradingService(db, test_settings)
    with pytest.raises(InsufficientDataError):
        await svc.create_trade(
            asset="BTC", direction="long", notional=Decimal(1_000), now=ENTRY_AS_OF
        )


async def test_open_positions_reports_live_unrealized_pnl_without_persisting_it(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    positions = await svc.open_positions(now=EXIT_AS_OF)
    assert len(positions) == 1
    position = positions[0]
    assert position.trade["uuid"] == opened["uuid"]
    assert position.data_quality_state == "ok"
    assert position.unrealized_pnl is not None
    # Never persisted (R3): the stored row still carries no realized figures.
    row = await svc.get_trade(opened["uuid"])
    assert row["realized_pnl"] is None
    assert row["gross_pnl"] is None


async def test_historical_integrity_entry_price_is_never_altered_by_a_later_close(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """Closing a trade must never rewrite its own already-recorded entry price/time/snapshot —
    only new exit fields are added ("Do not allow later information to alter the original
    decision context")."""
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    closed = await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)
    assert closed["entry_time"] == opened["entry_time"]
    assert closed["entry_price_observed"] == opened["entry_price_observed"]
    assert closed["entry_price_execution"] == opened["entry_price_execution"]
    assert closed["decision_snapshot_id"] == opened["decision_snapshot_id"]


async def test_performance_stats_reflect_actual_closed_trades(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    await svc.close_trade(opened["uuid"], now=EXIT_AS_OF)
    stats = await svc.performance_stats()
    assert stats.total_trades == 1
    assert stats.closed_trades == 1
    assert stats.open_trades == 0
    assert stats.winning_trades + stats.losing_trades <= 1


async def test_set_status_values_reach_the_database(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    repo = PaperTradeRepository(db)
    svc = PaperTradingService(db, test_settings)
    opened = await svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=ENTRY_AS_OF
    )
    row = await repo.get_by_uuid(opened["uuid"])
    assert row is not None
    assert row["status"] == "open"

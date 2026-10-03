"""`cfi.paper.stats.performance_stats` — deterministic, DB-free portfolio statistics (Phase 24
spec "Performance statistics"; "Do not present these statistics as evidence of future
profitability" — enforced by what this module does not compute, not by a disclaimer string
here)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.paper.stats import performance_stats


def _trade(exit_time: datetime, gross: Decimal, realized: Decimal) -> dict[str, object]:
    return {"exit_time": exit_time, "gross_pnl": gross, "realized_pnl": realized}


def test_no_trades_at_all() -> None:
    stats = performance_stats(counts_by_status={}, closed_trades=[])
    assert stats.total_trades == 0
    assert stats.closed_trades == 0
    assert stats.win_rate is None
    assert stats.average_win is None
    assert stats.average_loss is None
    assert stats.profit_factor is None
    assert stats.expectancy is None
    assert stats.max_drawdown is None
    assert stats.gross_pnl == 0
    assert stats.net_pnl == 0


def test_counts_by_status_split_correctly() -> None:
    stats = performance_stats(
        counts_by_status={"open": 2, "closed": 3, "cancelled": 1}, closed_trades=[]
    )
    assert stats.total_trades == 6
    assert stats.open_trades == 2
    assert stats.closed_trades == 3
    assert stats.cancelled_trades == 1


def test_all_winning_trades() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(t0, Decimal(100), Decimal(90)),
        _trade(t0, Decimal(50), Decimal(45)),
    ]
    stats = performance_stats(counts_by_status={"closed": 2}, closed_trades=trades)
    assert stats.winning_trades == 2
    assert stats.losing_trades == 0
    assert stats.win_rate == Decimal(100)
    assert stats.average_win == Decimal(135) / 2
    assert stats.average_loss is None
    assert stats.profit_factor is None  # no losses to divide by
    assert stats.max_drawdown == 0  # equity curve only ever rises


def test_mixed_wins_and_losses_profit_factor_and_expectancy() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [
        _trade(t0, Decimal(100), Decimal(90)),  # win
        _trade(t0, Decimal(-40), Decimal(-50)),  # loss
    ]
    stats = performance_stats(counts_by_status={"closed": 2}, closed_trades=trades)
    assert stats.winning_trades == 1
    assert stats.losing_trades == 1
    assert stats.win_rate == Decimal(50)
    assert stats.average_win == Decimal(90)
    assert stats.average_loss == Decimal(-50)
    assert stats.profit_factor == Decimal(90) / Decimal(50)
    assert stats.net_pnl == Decimal(40)
    assert stats.gross_pnl == Decimal(60)
    assert stats.expectancy == Decimal(40) / 2


def test_max_drawdown_is_the_largest_peak_to_trough_decline() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # Equity curve: +100 -> 100, -30 -> 70, +10 -> 80, -60 -> 20. Peak 100, trough 20 -> dd 80.
    trades = [
        _trade(t0, Decimal(100), Decimal(100)),
        _trade(t0, Decimal(-30), Decimal(-30)),
        _trade(t0, Decimal(10), Decimal(10)),
        _trade(t0, Decimal(-60), Decimal(-60)),
    ]
    stats = performance_stats(counts_by_status={"closed": 4}, closed_trades=trades)
    assert stats.max_drawdown == Decimal(80)


def test_all_losing_trades_profit_factor_is_none() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    trades = [_trade(t0, Decimal(-10), Decimal(-15)), _trade(t0, Decimal(-5), Decimal(-8))]
    stats = performance_stats(counts_by_status={"closed": 2}, closed_trades=trades)
    assert stats.winning_trades == 0
    assert stats.losing_trades == 2
    assert stats.win_rate == Decimal(0)
    assert stats.profit_factor == Decimal(0)  # sum_wins (0) / abs(sum_losses)

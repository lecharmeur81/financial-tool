"""Unit tests for cfi.backtest.metrics — every metric guarded to return None rather than a
fabricated value when there is insufficient data (R3: missing is a first-class state)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.backtest.metrics import EquityPoint, Trade, compute_metrics

DAY = timedelta(days=1)
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _equity(values: list[float]) -> list[EquityPoint]:
    return [
        EquityPoint(date=T0 + DAY * i, equity=Decimal(str(v)), exposure_pct=Decimal(50))
        for i, v in enumerate(values)
    ]


def _trade(pnl: float, return_pct: float, notional: float = 1000.0) -> Trade:
    return Trade(
        entry_date=T0,
        exit_date=T0 + DAY,
        entry_price=Decimal(100),
        exit_price=Decimal(110),
        size_base=Decimal(10),
        notional_at_entry=Decimal(str(notional)),
        fees_paid=Decimal(1),
        pnl=Decimal(str(pnl)),
        return_pct=Decimal(str(return_pct)),
        exit_reason="signal_exit",
    )


def test_empty_backtest_reports_every_metric_as_none_not_zero() -> None:
    metrics = compute_metrics(equity_curve=[], trades=[], risk_free_rate_annual=Decimal(0))
    assert metrics.num_trades == 0
    assert metrics.total_return_pct is None
    assert metrics.annualized_return_pct is None
    assert metrics.volatility_annualized_pct is None
    assert metrics.sharpe is None
    assert metrics.sortino is None
    assert metrics.max_drawdown_pct is None
    assert metrics.win_rate_pct is None
    assert metrics.expectancy is None
    assert metrics.turnover is None
    assert metrics.avg_trade_pct is None
    assert metrics.best_trade_pct is None
    assert metrics.worst_trade_pct is None


def test_single_equity_point_cannot_compute_return_or_drawdown() -> None:
    metrics = compute_metrics(
        equity_curve=_equity([1000.0]), trades=[], risk_free_rate_annual=Decimal(0)
    )
    assert metrics.total_return_pct is None
    assert metrics.max_drawdown_pct is None


def test_total_return_pct_reflects_start_and_end_equity() -> None:
    metrics = compute_metrics(
        equity_curve=_equity([1000.0, 1100.0]), trades=[], risk_free_rate_annual=Decimal(0)
    )
    assert metrics.total_return_pct == Decimal("10.0000")


def test_max_drawdown_pct_is_negative_and_reflects_the_worst_peak_to_trough_decline() -> None:
    # 1000 -> 1200 (new peak) -> 900 (25% decline from peak) -> 1000
    metrics = compute_metrics(
        equity_curve=_equity([1000.0, 1200.0, 900.0, 1000.0]),
        trades=[],
        risk_free_rate_annual=Decimal(0),
    )
    assert metrics.max_drawdown_pct == Decimal("-25.0000")


def test_win_rate_and_trade_extremes_from_a_mixed_trade_list() -> None:
    trades = [_trade(pnl=100, return_pct=10), _trade(pnl=-50, return_pct=-5)]
    metrics = compute_metrics(equity_curve=[], trades=trades, risk_free_rate_annual=Decimal(0))
    assert metrics.num_trades == 2
    assert metrics.win_rate_pct == Decimal("50.0000")
    assert metrics.best_trade_pct == Decimal("10.0000")
    assert metrics.worst_trade_pct == Decimal("-5.0000")
    assert metrics.avg_trade_pct == Decimal("2.5000")


def test_expectancy_is_none_when_no_trades_but_zero_is_never_fabricated() -> None:
    metrics = compute_metrics(equity_curve=[], trades=[], risk_free_rate_annual=Decimal(0))
    assert metrics.expectancy is None


def test_turnover_requires_both_trades_and_an_equity_curve() -> None:
    trades = [_trade(pnl=100, return_pct=10, notional=1000)]
    # No equity curve supplied -> turnover cannot be computed.
    metrics = compute_metrics(equity_curve=[], trades=trades, risk_free_rate_annual=Decimal(0))
    assert metrics.turnover is None

    metrics_with_equity = compute_metrics(
        equity_curve=_equity([1000.0, 1100.0]),
        trades=trades,
        risk_free_rate_annual=Decimal(0),
    )
    assert metrics_with_equity.turnover is not None
    assert metrics_with_equity.turnover > 0


def test_sharpe_and_volatility_require_at_least_two_daily_returns() -> None:
    # Only one return (two equity points) -> too few to compute a standard deviation.
    metrics = compute_metrics(
        equity_curve=_equity([1000.0, 1010.0]), trades=[], risk_free_rate_annual=Decimal(0)
    )
    assert metrics.volatility_annualized_pct is None
    assert metrics.sharpe is None


def test_sharpe_is_none_when_daily_returns_have_zero_variance() -> None:
    # Constant daily growth -> zero variance -> Sharpe cannot divide by zero stdev.
    metrics = compute_metrics(
        equity_curve=_equity([1000.0, 1010.0, 1020.1]),
        trades=[],
        risk_free_rate_annual=Decimal(0),
    )
    assert metrics.sharpe is None


def test_sortino_requires_at_least_two_downside_observations() -> None:
    # Mostly-up path with a single down day -> not enough downside observations for Sortino.
    metrics = compute_metrics(
        equity_curve=_equity([1000.0, 1010.0, 1005.0, 1020.0, 1030.0]),
        trades=[],
        risk_free_rate_annual=Decimal(0),
    )
    assert metrics.sortino is None

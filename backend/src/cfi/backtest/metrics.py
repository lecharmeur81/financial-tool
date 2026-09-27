"""Performance metrics computed from a completed backtest's trade list and daily equity curve
(Phase 16). Pure functions, stdlib ``Decimal``/``statistics`` only — this codebase has no numpy/
pandas/scipy dependency anywhere (confirmed by survey before this phase was built), and these
metrics do not need one.

Every metric that cannot be computed (too few trades, zero variance, an incomplete equity curve)
is reported as ``None`` with the reason implicit in ``BacktestMetrics``'s own docstring — never a
fabricated zero (R3: missing is a first-class state).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from cfi.backtest.universe import TRADING_DAYS_PER_YEAR


@dataclass(frozen=True, slots=True)
class Trade:
    entry_date: datetime
    exit_date: datetime
    entry_price: Decimal
    exit_price: Decimal
    size_base: Decimal
    notional_at_entry: Decimal
    fees_paid: Decimal
    pnl: Decimal
    return_pct: Decimal
    exit_reason: str  # "signal_exit"|"stop_loss"|"take_profit"|"time_exit"|"end_of_backtest"


@dataclass(frozen=True, slots=True)
class EquityPoint:
    date: datetime
    equity: Decimal
    exposure_pct: Decimal


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    total_return_pct: Decimal | None
    annualized_return_pct: Decimal | None
    volatility_annualized_pct: Decimal | None
    max_drawdown_pct: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    win_rate_pct: Decimal | None
    expectancy: Decimal | None
    turnover: Decimal | None
    avg_exposure_pct: Decimal | None
    num_trades: int
    avg_trade_pct: Decimal | None
    best_trade_pct: Decimal | None
    worst_trade_pct: Decimal | None


def _q(value: Decimal) -> Decimal:
    try:
        return value.quantize(Decimal("0.0001"))
    except InvalidOperation:  # pragma: no cover — guards against non-finite Decimals
        return value


def _daily_returns(equity_curve: list[EquityPoint]) -> list[Decimal]:
    out: list[Decimal] = []
    for prior, current in pairwise(equity_curve):
        if prior.equity > 0:
            out.append(current.equity / prior.equity - 1)
    return out


def _max_drawdown_pct(equity_curve: list[EquityPoint]) -> Decimal | None:
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0].equity
    worst = Decimal(0)
    for point in equity_curve:
        if point.equity > peak:
            peak = point.equity
        if peak > 0:
            decline = (point.equity - peak) / peak * 100
            if decline < worst:
                worst = decline
    return _q(worst)


def compute_metrics(
    *, equity_curve: list[EquityPoint], trades: list[Trade], risk_free_rate_annual: Decimal
) -> BacktestMetrics:
    num_trades = len(trades)

    total_return_pct: Decimal | None = None
    annualized_return_pct: Decimal | None = None
    volatility_annualized_pct: Decimal | None = None
    sharpe: Decimal | None = None
    sortino: Decimal | None = None
    avg_exposure_pct: Decimal | None = None

    if len(equity_curve) >= 2 and equity_curve[0].equity > 0:
        total_return_pct = _q((equity_curve[-1].equity / equity_curve[0].equity - 1) * 100)
        span_days = (equity_curve[-1].date - equity_curve[0].date).days
        if span_days > 0:
            growth = equity_curve[-1].equity / equity_curve[0].equity
            annualized_return_pct = _q(
                (growth ** (Decimal(TRADING_DAYS_PER_YEAR) / Decimal(span_days)) - 1) * 100
            )

        daily_returns = _daily_returns(equity_curve)
        if len(daily_returns) >= 2:
            stdev = Decimal(str(statistics.pstdev(daily_returns)))
            volatility_annualized_pct = _q(stdev * Decimal(TRADING_DAYS_PER_YEAR).sqrt() * 100)
            daily_rf = risk_free_rate_annual / 100 / TRADING_DAYS_PER_YEAR
            mean_return = Decimal(str(statistics.fmean(daily_returns)))
            if stdev > 0:
                sharpe = _q(
                    (mean_return - daily_rf) / stdev * Decimal(TRADING_DAYS_PER_YEAR).sqrt()
                )
            downside = [r for r in daily_returns if r < daily_rf]
            if len(downside) >= 2:
                downside_dev = Decimal(str(statistics.pstdev(downside)))
                if downside_dev > 0:
                    sortino = _q(
                        (mean_return - daily_rf)
                        / downside_dev
                        * Decimal(TRADING_DAYS_PER_YEAR).sqrt()
                    )

        avg_exposure_pct = _q(Decimal(str(statistics.fmean(p.exposure_pct for p in equity_curve))))

    max_drawdown_pct = _max_drawdown_pct(equity_curve)

    win_rate_pct: Decimal | None = None
    expectancy: Decimal | None = None
    turnover: Decimal | None = None
    avg_trade_pct: Decimal | None = None
    best_trade_pct: Decimal | None = None
    worst_trade_pct: Decimal | None = None

    if num_trades > 0:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        win_rate = Decimal(len(wins)) / Decimal(num_trades)
        win_rate_pct = _q(win_rate * 100)
        avg_win = Decimal(str(statistics.fmean(t.pnl for t in wins))) if wins else Decimal(0)
        avg_loss = (
            Decimal(str(statistics.fmean(abs(t.pnl) for t in losses))) if losses else Decimal(0)
        )
        loss_rate = 1 - win_rate
        expectancy = _q(win_rate * avg_win - loss_rate * avg_loss)

        returns = [t.return_pct for t in trades]
        avg_trade_pct = _q(Decimal(str(statistics.fmean(returns))))
        best_trade_pct = _q(max(returns))
        worst_trade_pct = _q(min(returns))

        if len(equity_curve) >= 2:
            avg_equity = Decimal(str(statistics.fmean(p.equity for p in equity_curve)))
            if avg_equity > 0:
                total_traded_notional = sum(
                    (t.notional_at_entry + t.size_base * t.exit_price for t in trades), Decimal(0)
                )
                turnover = _q(total_traded_notional / avg_equity)

    return BacktestMetrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        volatility_annualized_pct=volatility_annualized_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe=sharpe,
        sortino=sortino,
        win_rate_pct=win_rate_pct,
        expectancy=expectancy,
        turnover=turnover,
        avg_exposure_pct=avg_exposure_pct,
        num_trades=num_trades,
        avg_trade_pct=avg_trade_pct,
        best_trade_pct=best_trade_pct,
        worst_trade_pct=worst_trade_pct,
    )

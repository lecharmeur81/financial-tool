"""Deterministic portfolio/trade statistics (Phase 24 spec "Performance statistics") — a pure
function over already-persisted trade rows, computed live on every request rather than maintained
as a separate, driftable counter (R3, same posture as
``cfi.analyst.repository.AnalystRepository.monthly_cost_usd``).

These are descriptive statistics about trades the user already recorded — never a forecast and
never presented as evidence of future profitability ("Do not present these statistics as evidence
of future profitability" — enforced here by what this module does *not* compute: no projection, no
confidence interval, no "expected future return")."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class PerformanceStats:
    total_trades: int
    open_trades: int
    closed_trades: int
    cancelled_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    gross_pnl: Decimal
    net_pnl: Decimal
    average_win: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    max_drawdown: Decimal | None


def performance_stats(
    *, counts_by_status: dict[str, int], closed_trades: list[dict[str, Any]]
) -> PerformanceStats:
    """``closed_trades`` must be ordered by ``exit_time`` ascending (the repository's
    ``list_closed`` already guarantees this) — required for ``max_drawdown``'s running equity
    curve, which must process trades in the order they actually closed, never reordered by size
    or outcome."""
    open_trades = counts_by_status.get("open", 0)
    closed = counts_by_status.get("closed", 0)
    cancelled = counts_by_status.get("cancelled", 0)
    total = open_trades + closed + cancelled

    wins = [t for t in closed_trades if t["realized_pnl"] is not None and t["realized_pnl"] > 0]
    losses = [t for t in closed_trades if t["realized_pnl"] is not None and t["realized_pnl"] < 0]
    winning_trades = len(wins)
    losing_trades = len(losses)

    win_rate = Decimal(winning_trades) / Decimal(closed) * 100 if closed > 0 else None

    gross_pnl = sum((Decimal(t["gross_pnl"]) for t in closed_trades), Decimal(0))
    net_pnl = sum((Decimal(t["realized_pnl"]) for t in closed_trades), Decimal(0))

    sum_wins = sum((Decimal(t["realized_pnl"]) for t in wins), Decimal(0))
    sum_losses = sum((Decimal(t["realized_pnl"]) for t in losses), Decimal(0))  # <= 0

    average_win = sum_wins / winning_trades if winning_trades > 0 else None
    average_loss = sum_losses / losing_trades if losing_trades > 0 else None

    profit_factor = (sum_wins / abs(sum_losses)) if sum_losses != 0 else None

    expectancy = net_pnl / closed if closed > 0 else None

    max_drawdown = _max_drawdown(closed_trades)

    return PerformanceStats(
        total_trades=total,
        open_trades=open_trades,
        closed_trades=closed,
        cancelled_trades=cancelled,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        average_win=average_win,
        average_loss=average_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=max_drawdown,
    )


def _max_drawdown(closed_trades: list[dict[str, Any]]) -> Decimal | None:
    """Maximum peak-to-trough decline of the cumulative realized-P&L equity curve, built from
    trades in the order they closed. ``None`` when no closed trade exists yet ("where
    meaningful" — an empty or single-trade curve has no meaningful drawdown to report)."""
    if not closed_trades:
        return None
    cumulative = Decimal(0)
    peak = Decimal(0)
    max_dd = Decimal(0)
    for trade in closed_trades:
        cumulative += Decimal(trade["realized_pnl"])
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd

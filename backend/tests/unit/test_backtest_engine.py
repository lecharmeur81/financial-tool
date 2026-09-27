"""Unit tests for the pure, DB-independent helper functions inside cfi.backtest.engine.

These exercise the exact code paths behind RED_TEAM_REPORT.md findings #3 (stop-loss/take-profit
slippage + gap handling), #5 (size-dependent slippage), and #14 (silent warmup shortfall) directly
against hand-computed expected values — no database, no event loop, no fake providers required.
Full end-to-end wiring (a real ``run_backtest`` call producing these same fills through the whole
loop) is covered by ``tests/integration/test_backtest_engine.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.backtest.costs import COST_MODEL_V2
from cfi.backtest.engine import (
    _intrabar_stop_fill,
    _participation_fraction,
    _Position,
    _warmup_shortfall_warning,
)
from cfi.backtest.strategy import StopConditions
from cfi.backtest.universe import WARMUP_DAYS
from cfi.market_structure.metrics import Bar

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _position(entry_price: Decimal) -> _Position:
    return _Position(
        entry_date=T0,
        entry_price=entry_price,
        size_base=Decimal(1),
        notional_at_entry=entry_price,
        entry_fee=Decimal(0),
        last_mark_price=entry_price,
    )


def _bar(*, open_: Decimal, high: Decimal, low: Decimal, close: Decimal) -> Bar:
    return Bar(time=T0, open=open_, high=high, low=low, close=close, volume=None)


# --- _intrabar_stop_fill: finding #3 ----------------------------------------------------------


def test_no_stop_configured_never_fires() -> None:
    position = _position(Decimal(100))
    today = _bar(open_=Decimal(50), high=Decimal(200), low=Decimal(1), close=Decimal(100))
    assert _intrabar_stop_fill(position, today, StopConditions()) is None


def test_stop_loss_pierced_by_low_without_gap_fills_at_exact_stop_level() -> None:
    """entry=100, stop_loss_pct=10 -> sl=90. Open(95) stays above sl; low(88) pierces it."""
    position = _position(Decimal(100))
    today = _bar(open_=Decimal(95), high=Decimal(96), low=Decimal(88), close=Decimal(90))
    result = _intrabar_stop_fill(position, today, StopConditions(stop_loss_pct=Decimal(10)))
    assert result == ("stop_loss", Decimal(90))  # the raw stop level itself, not the open


def test_stop_loss_gapped_through_by_open_fills_at_the_open_not_the_stop_level() -> None:
    """entry=100, stop_loss_pct=10 -> sl=90. Open(85) has already gapped below sl before the bar
    even began — the worst real price achievable that day is the open, not the stale sl level."""
    position = _position(Decimal(100))
    today = _bar(open_=Decimal(85), high=Decimal(87), low=Decimal(80), close=Decimal(82))
    result = _intrabar_stop_fill(position, today, StopConditions(stop_loss_pct=Decimal(10)))
    assert result == ("stop_loss", Decimal(85))  # the open, worse than sl=90


def test_take_profit_pierced_by_high_without_gap_fills_at_exact_tp_level() -> None:
    """entry=100, take_profit_pct=20 -> tp=120. Open(110) stays below tp; high(125) pierces it."""
    position = _position(Decimal(100))
    today = _bar(open_=Decimal(110), high=Decimal(125), low=Decimal(108), close=Decimal(120))
    result = _intrabar_stop_fill(position, today, StopConditions(take_profit_pct=Decimal(20)))
    assert result == ("take_profit", Decimal(120))


def test_take_profit_gapped_through_by_open_fills_at_the_open_not_the_tp_level() -> None:
    """entry=100, take_profit_pct=20 -> tp=120. Open(130) already gapped above tp before the bar
    began — fills at that open, not the stale tp level."""
    position = _position(Decimal(100))
    today = _bar(open_=Decimal(130), high=Decimal(135), low=Decimal(128), close=Decimal(132))
    result = _intrabar_stop_fill(position, today, StopConditions(take_profit_pct=Decimal(20)))
    assert result == ("take_profit", Decimal(130))


def test_stop_loss_is_checked_before_take_profit_when_both_configured() -> None:
    """If a bar's range spans both levels (a wide, volatile day), the stop-loss (capital
    preservation) takes priority over the take-profit — a documented tie-break, not an accident."""
    position = _position(Decimal(100))
    stops = StopConditions(stop_loss_pct=Decimal(10), take_profit_pct=Decimal(20))
    today = _bar(open_=Decimal(100), high=Decimal(125), low=Decimal(85), close=Decimal(100))
    result = _intrabar_stop_fill(position, today, stops)
    assert result is not None
    assert result[0] == "stop_loss"


def test_neither_level_breached_returns_none() -> None:
    position = _position(Decimal(100))
    stops = StopConditions(stop_loss_pct=Decimal(10), take_profit_pct=Decimal(20))
    today = _bar(open_=Decimal(100), high=Decimal(105), low=Decimal(95), close=Decimal(100))
    assert _intrabar_stop_fill(position, today, stops) is None


# --- _participation_fraction: finding #5 ------------------------------------------------------


def test_participation_fraction_is_none_without_enough_trailing_volume() -> None:
    bars = [_bar(open_=Decimal(100), high=Decimal(100), low=Decimal(100), close=Decimal(100))]
    assert _participation_fraction(Decimal(1000), bars, Decimal(100), COST_MODEL_V2) is None


def test_participation_fraction_is_notional_over_liquidity_cap() -> None:
    bars = [
        Bar(
            time=T0,
            open=Decimal(10),
            high=Decimal(10),
            low=Decimal(10),
            close=Decimal(10),
            volume=Decimal(1000),
        )
        for _ in range(20)
    ]
    # trailing_avg_volume = 1000; liquidity_cap = 1000 * price(100) * 5% = 5000
    fraction = _participation_fraction(Decimal(2500), bars, Decimal(100), COST_MODEL_V2)
    assert fraction == Decimal(2500) / Decimal(5000)
    assert fraction == Decimal("0.5")


# --- _warmup_shortfall_warning: finding #14 ----------------------------------------------------


def test_warmup_shortfall_warns_when_fewer_bars_than_warmup_days_are_available() -> None:
    bars = [_bar(open_=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1))] * 10
    warning = _warmup_shortfall_warning(bars, start_idx=5)
    assert warning is not None
    assert "5 bar(s)" in warning
    assert str(WARMUP_DAYS) in warning


def test_no_warmup_warning_when_enough_bars_are_available() -> None:
    bars = [_bar(open_=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1))] * (
        WARMUP_DAYS + 10
    )
    assert _warmup_shortfall_warning(bars, start_idx=WARMUP_DAYS) is None

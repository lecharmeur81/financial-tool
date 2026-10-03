"""Deterministic P&L calculations for paper trading (Phase 24 spec "P&L calculations") — pure
functions, no I/O, exactly the discipline ``cfi.divergence.metrics``/``cfi.backtest.costs``
already follow in this codebase (R13: reuse the established style, do not invent a parallel one).

**Pipeline (Phase 24 spec "Entry and exit": "Clearly distinguish: Observed market price →
simulated execution price → calculated P&L"):**

1. An *observed* price is read from the market (``cfi.divergence.adapters.Adapters.price_close``)
   — never fabricated, never a real exchange execution.
2. A *simulated execution* price is derived from it by ``cfi.backtest.costs.slipped_price``,
   reused unchanged — always adverse to the trader (buying pays more, selling receives less),
   exactly as the backtest engine already defines it.
3. P&L is calculated from the two simulated execution prices, broken into explicit components
   that reconcile additively:

   ``gross_pnl`` — the pure price-move result, computed from the two *observed* prices (what the
   market actually did, with no cost assumption at all).

   ``slippage_cost`` — the dollar cost of execution slippage on both legs (entry + exit), always
   non-negative by construction (slippage is always adverse).

   ``fees_total`` — the proportional fee charged on both legs (``cfi.backtest.costs.apply_fee``),
   each computed on that leg's own simulated-execution notional.

   ``net_pnl = gross_pnl - slippage_cost - fees_total`` (equivalently, the price-move result
   computed directly from the two *execution* prices, minus fees — both give the identical
   figure; the explicit subtraction form is used so the three cost components are individually
   visible, per the spec's own itemised list).

   ``return_pct = net_pnl / margin * 100`` where ``margin = notional / leverage`` is the capital
   actually at risk — leverage amplifies the *return*, not the underlying price move, which is
   exactly the distinction the spec's "Handle leverage correctly without confusing leveraged
   exposure with actual P&L" instruction asks to preserve: ``gross_pnl``/``net_pnl`` in dollar
   terms never depend on leverage (only on ``notional``, which is the actual simulated position
   size), while ``return_pct`` does.

**Units:** prices are USD per unit of the asset; ``notional``/``margin``/P&L figures are USD;
``return_pct`` is a percentage of margin; ``quantity`` is in units of the asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from cfi.backtest.costs import CostParameterSet, apply_fee, slipped_price
from cfi.divergence.metrics import Series, window_reading

Direction = Literal["long", "short"]
Leg = Literal["entry", "exit"]


def execution_side(direction: Direction, leg: Leg) -> str:
    """The ``slipped_price``/order side for one leg of a trade.

    A long position buys to open and sells to close; a short position sells (short-sells) to
    open and buys to close. Each leg is always priced against the trader (``slipped_price``'s own
    contract) — this mapping is what makes that adverse-pricing rule apply correctly to both
    directions."""
    if direction == "long":
        return "buy" if leg == "entry" else "sell"
    return "sell" if leg == "entry" else "buy"


def execution_price(
    observed_price: Decimal, *, direction: Direction, leg: Leg, params: CostParameterSet
) -> Decimal:
    """The simulated execution price for one leg — step 2 of the pipeline. No participation-
    scaled slippage is applied (``participation_fraction`` is left ``None``): modelling liquidity
    impact meaningfully needs the position-sizing context the backtest engine builds for itself
    (ADR-0061), which does not naturally apply to an arbitrary user-specified notional — a
    documented limitation, not an oversight (DECISIONS.md)."""
    return slipped_price(observed_price, direction=execution_side(direction, leg), params=params)


def current_price(points: Series, as_of: datetime) -> Decimal | None:
    """The latest known observed price at or before ``as_of`` — reuses
    ``cfi.divergence.metrics.window_reading`` unchanged with ``window_days=0``, which collapses
    its own "now" and "window-ago" lookups onto the same point, so ``last_value`` is exactly the
    most recent valued point at or before ``as_of`` (``None`` if none exists — R3, missing is a
    first-class state, never guessed)."""
    reading = window_reading(points, as_of, window_days=0)
    if reading.status != "ok":
        return None
    return reading.last_value


@dataclass(frozen=True, slots=True)
class PnLResult:
    quantity: Decimal
    gross_pnl: Decimal
    slippage_cost: Decimal
    fees_total: Decimal
    net_pnl: Decimal
    return_pct: Decimal
    margin: Decimal


def calculate_pnl(
    *,
    direction: Direction,
    notional: Decimal,
    leverage: Decimal,
    entry_price_observed: Decimal,
    entry_price_execution: Decimal,
    exit_price_observed: Decimal,
    exit_price_execution: Decimal,
    params: CostParameterSet,
) -> PnLResult:
    """Step 3 of the pipeline — see module docstring for the full derivation. Used both for a
    real close (persisted) and for a live "if closed now" unrealized-P&L preview on an open
    position (never persisted — see ``cfi.paper.service``); the two call sites share this one
    function so the methodology is identical in both cases (R13: no parallel calculation)."""
    quantity = notional / entry_price_execution
    margin = notional / leverage

    sign = Decimal(1) if direction == "long" else Decimal(-1)
    gross_pnl = quantity * sign * (exit_price_observed - entry_price_observed)

    entry_fee = apply_fee(quantity * entry_price_execution, params)
    exit_fee = apply_fee(quantity * exit_price_execution, params)
    fees_total = entry_fee + exit_fee

    # Always non-negative: both legs' execution prices are adverse relative to their observed
    # prices by construction (``slipped_price``), so this is a genuine cost, never a credit.
    entry_slippage = quantity * abs(entry_price_execution - entry_price_observed)
    exit_slippage = quantity * abs(exit_price_execution - exit_price_observed)
    slippage_cost = entry_slippage + exit_slippage

    net_pnl = gross_pnl - slippage_cost - fees_total
    return_pct = (net_pnl / margin * 100) if margin != 0 else Decimal(0)

    return PnLResult(
        quantity=quantity,
        gross_pnl=gross_pnl,
        slippage_cost=slippage_cost,
        fees_total=fees_total,
        net_pnl=net_pnl,
        return_pct=return_pct,
        margin=margin,
    )


@dataclass(frozen=True, slots=True)
class MaxMove:
    favorable_pct: Decimal | None
    adverse_pct: Decimal | None


def max_favorable_adverse(
    direction: Direction, entry_price_observed: Decimal, path_prices: list[Decimal]
) -> MaxMove:
    """Maximum favorable/adverse movement over the trade's holding period ("P&L calculations":
    "Maximum favorable/adverse movement where supported"), expressed as a percentage of the entry
    observed price. ``path_prices`` is the already-point-in-time-filtered sequence of daily
    observed closes from entry to exit inclusive (``cfi.divergence.adapters.Adapters.price_close``
    — the caller is responsible for the time-window filtering, so this function stays pure).

    "Where supported": an empty ``path_prices`` (no daily closes available over the holding
    period — e.g. the trade's lookback exceeds the adapter's loaded span) returns ``None`` for
    both fields rather than guessing (R3)."""
    if not path_prices:
        return MaxMove(None, None)
    if entry_price_observed == 0:
        return MaxMove(None, None)
    highest = max(path_prices)
    lowest = min(path_prices)
    if direction == "long":
        favorable = (highest - entry_price_observed) / entry_price_observed * 100
        adverse = (lowest - entry_price_observed) / entry_price_observed * 100
    else:
        favorable = (entry_price_observed - lowest) / entry_price_observed * 100
        adverse = (entry_price_observed - highest) / entry_price_observed * 100
    return MaxMove(favorable, adverse)

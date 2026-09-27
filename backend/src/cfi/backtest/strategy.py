"""Strategy definitions (Phase 16): entry rules, exit rules, position sizing, stop conditions,
time-based exits, and leverage/exposure limits, composed into one versioned, reproducible
``StrategyDefinition``.

**Scope decision (ADR-0059, documented, not silently narrowed):** v1 supports **long-only**
strategies (hold BTC, sized up to a leverage limit, or hold cash) — the user's Phase 16 spec lists
"exposure" and "leverage" but never "short selling" or "long/short," and long-only already exercises
every one of those two requirements (leverage > 1x borrows capital to hold more BTC than equity
alone would buy; exposure ranges 0..leverage). Short selling / long-short strategies are a natural
future extension, not implemented here.

Two example strategies are provided (``EXAMPLE_STRATEGIES``) purely to illustrate the shape of a
complete, runnable ``StrategyDefinition`` and to exercise the engine's own tests — **their
parameters are v1 judgment defaults, chosen by design and never fitted or optimized against any
backtest result** (this phase's explicit instruction: "Do not optimize parameters against the test
set"). A real research strategy is the user's own to define and version.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from cfi.backtest.signals import PRICE_SIGNALS, Signal, domain_signal

Comparator = Literal["gte", "lte"]
PositionSizingMethod = Literal["fixed_fraction", "fixed_notional", "volatility_target"]


def compare(value: Decimal, comparator: Comparator, threshold: Decimal) -> bool:
    if comparator == "gte":
        return value >= threshold
    if comparator == "lte":
        return value <= threshold
    raise ValueError(f"unknown comparator: {comparator!r}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class PositionSizing:
    method: PositionSizingMethod
    value: Decimal
    # fixed_fraction: `value` is the fraction of equity to hold (e.g. 0.5 = 50%, 1.5 = 150% via
    #   leverage, capped by RiskLimits.max_leverage).
    # fixed_notional: `value` is a fixed currency notional per position (still capped by
    #   RiskLimits and the liquidity constraint).
    # volatility_target: `value` is a target ANNUALIZED volatility (%); notional is sized so the
    #   position's own realized volatility (cfi.market_structure.metrics.realized_volatility)
    #   through the decision day matches that target — smaller positions when BTC is more
    #   volatile, larger when calmer, still capped by RiskLimits.


@dataclass(frozen=True, slots=True)
class StopConditions:
    stop_loss_pct: Decimal | None = None  # e.g. Decimal("10") = exit if price falls 10% from entry
    take_profit_pct: Decimal | None = None  # e.g. Decimal("20") = exit if price rises 20%


@dataclass(frozen=True, slots=True)
class TimeExit:
    max_holding_days: int | None = None  # exit if still open this many days after entry


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_leverage: Decimal = Decimal(1)  # position notional <= equity * max_leverage
    max_exposure_pct: Decimal = Decimal(100)  # position notional <= equity * max_exposure_pct/100


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    version: str
    signal: Signal
    entry_comparator: Comparator
    entry_threshold: Decimal
    exit_comparator: Comparator
    exit_threshold: Decimal
    position_sizing: PositionSizing
    stops: StopConditions
    time_exit: TimeExit
    risk_limits: RiskLimits
    description: str = ""


EXAMPLE_STRATEGIES: dict[str, StrategyDefinition] = {
    "sma_trend_follow_v1": StrategyDefinition(
        strategy_id="sma_trend_follow",
        version="sma_trend_follow_v1",
        signal=PRICE_SIGNALS["sma_crossover"],
        entry_comparator="gte",
        entry_threshold=Decimal(0),
        exit_comparator="lte",
        exit_threshold=Decimal(0),
        position_sizing=PositionSizing(method="fixed_fraction", value=Decimal("0.5")),
        stops=StopConditions(stop_loss_pct=Decimal("10"), take_profit_pct=Decimal("20")),
        time_exit=TimeExit(max_holding_days=90),
        risk_limits=RiskLimits(max_leverage=Decimal(1), max_exposure_pct=Decimal(100)),
        description="Illustrative long-only SMA(20/50) trend follower. Enter when the fast SMA is "
        "above the slow SMA, exit when it crosses back below. Parameters are v1 defaults, not "
        "fitted to any data.",
    ),
    "whale_accumulation_v1": StrategyDefinition(
        strategy_id="whale_accumulation",
        version="whale_accumulation_v1",
        signal=domain_signal("whale_score"),
        entry_comparator="gte",
        entry_threshold=Decimal(15),  # the same accumulation threshold cfi.regime already uses
        exit_comparator="lte",
        exit_threshold=Decimal(-15),  # the symmetric distribution threshold on the same score
        position_sizing=PositionSizing(method="fixed_fraction", value=Decimal("0.3")),
        stops=StopConditions(stop_loss_pct=Decimal("15"), take_profit_pct=None),
        time_exit=TimeExit(max_holding_days=180),
        risk_limits=RiskLimits(max_leverage=Decimal(1), max_exposure_pct=Decimal(60)),
        description="Illustrative long-only strategy following cfi.whales' own whale_score: enter "
        "when whale flow reads as accumulating (>= 15, the same band cfi.regime's Accumulation "
        "regime uses), exit when it reads as distributing (<= -15). Parameters are v1 defaults, "
        "not fitted to any data.",
    ),
}

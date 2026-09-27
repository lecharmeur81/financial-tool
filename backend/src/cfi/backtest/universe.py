"""Constants for the Backtesting Engine (Phase 16). See ADR-0059 for rationale."""

from __future__ import annotations

BENCHMARK_ASSET = "BTC"

# Enough daily bars before the requested start date to warm up every built-in signal's longest
# lookback (SMA200 needs 200, RSI needs its period + 1) before the first simulated decision.
WARMUP_DAYS = 220

# Trailing window used to size a liquidity constraint — deliberately NOT the execution bar's own
# volume (not yet known when the decision is made): the trailing average through the decision day.
LIQUIDITY_LOOKBACK_DAYS = 20

# Annualization: crypto trades every calendar day (no market closure), unlike equities' 252.
TRADING_DAYS_PER_YEAR = 365

NOT_TRACKED: tuple[str, ...] = (
    "Only BTC is tradable (the platform's established benchmark asset) — no multi-asset universe, "
    "and so no survivorship-bias handling is implemented (there is no universe of assets to have "
    "survivors or delistings); this would need explicit point-in-time universe membership if a "
    "later phase adds more tradable assets.",
    "No parameter optimizer is included anywhere in this engine (this phase's explicit "
    "instruction). cfi.backtest.splits only partitions time into in-sample/validation/"
    "out-of-sample/walk-forward windows for the user to manually judge generalization of a FIXED, "
    "already-specified strategy — it never searches for or selects a 'best' parameter set.",
    "Signal-driven entries and exits execute at the following bar's open (never the deciding bar's "
    "own close) — a deliberate execution lag, not a data gap. Stop-loss/take-profit are the one "
    "exception: they are risk-management orders that trigger intrabar against that day's own "
    "high/low, slipped like any other fill, and filled at that day's own (slipped) open instead "
    "when the open already gapped through the stop/take-profit level (ADR-0061, Phase 18).",
)

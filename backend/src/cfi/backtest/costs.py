"""Versioned cost model — fees, slippage, and a liquidity participation cap (Phase 16).

Same convention as every other score/parameter set in this platform (frozen dataclass, an
append-only ``PARAMETER_SETS`` registry, a ``parameters(version)`` accessor raising a hard
``KeyError`` on an unknown version, R3). Values are v1 judgment defaults — generous, documented,
not fitted to data or empirically validated — awaiting the user's review, same posture as every
score band in this platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CostParameterSet:
    version: str
    fee_bps: Decimal  # proportional fee, applied to notional on both entry and exit
    slippage_bps: Decimal  # proportional adverse price adjustment applied at execution
    max_participation_pct: Decimal  # position notional capped at this % of trailing avg volume
    risk_free_rate_annual: Decimal  # for Sharpe/Sortino — a documented assumption, not fitted
    # ADR-0061 (Phase 18, RED_TEAM_REPORT.md finding #5): scales slipped_price's adverse
    # adjustment by how large the trade is relative to the day's liquidity cap
    # (participation_fraction = notional / liquidity_cap_notional, clamped to [0, 1]):
    #   effective_slippage_bps = slippage_bps * (1 + participation_impact_coefficient * fraction)
    # Zero (cost_model_v1's value) reproduces the original flat model exactly, so v1 runs remain
    # byte-for-byte reproducible. A non-zero coefficient (cost_model_v2) is a documented,
    # judgment-call magnitude, not fitted to data — same posture as every other cost parameter.
    participation_impact_coefficient: Decimal = Decimal("0")


COST_MODEL_V1 = CostParameterSet(
    version="cost_model_v1",
    fee_bps=Decimal("10"),  # 0.10% per side — a generic, documented spot-exchange-taker default
    slippage_bps=Decimal("5"),  # 0.05% adverse execution — a generic, documented default
    max_participation_pct=Decimal("5"),  # position notional capped at 5% of trailing avg volume
    risk_free_rate_annual=Decimal("0"),  # documented assumption: 0% — not a market forecast
    participation_impact_coefficient=Decimal("0"),  # preserved: v1 is deliberately flat
)

COST_MODEL_V2 = CostParameterSet(
    version="cost_model_v2",
    fee_bps=Decimal("10"),
    slippage_bps=Decimal("5"),
    max_participation_pct=Decimal("5"),
    risk_free_rate_annual=Decimal("0"),
    # A trade sized right at the participation cap pays double the base slippage; one at 50% of
    # the cap pays 1.5x. A documented judgment-call magnitude (linear-in-participation), not fitted.
    participation_impact_coefficient=Decimal("1"),
)

PARAMETER_SETS: dict[str, CostParameterSet] = {
    "cost_model_v1": COST_MODEL_V1,
    "cost_model_v2": COST_MODEL_V2,
}
CURRENT_VERSION = "cost_model_v2"


def parameters(version: str | None = None) -> CostParameterSet:
    v = version or CURRENT_VERSION
    if v not in PARAMETER_SETS:
        raise KeyError(f"unknown cost model version: {v!r}")
    return PARAMETER_SETS[v]


def apply_fee(notional: Decimal, params: CostParameterSet) -> Decimal:
    """The fee charged on one side (entry or exit) of a trade of this notional."""
    return notional * params.fee_bps / Decimal(10_000)


def slipped_price(
    price: Decimal,
    *,
    direction: str,
    params: CostParameterSet,
    participation_fraction: Decimal | None = None,
) -> Decimal:
    """The executed price after slippage — always adverse: worse for the trader than the quoted
    price, in the direction that direction's trade suffers (buying pays more, selling receives
    less).

    ``participation_fraction`` (ADR-0061, finding #5) is this trade's notional as a fraction of
    the day's liquidity cap notional (0 = negligible size, 1 = right at the participation cap;
    values are clamped to ``[0, 1]``, since sizing already enforces the cap upstream — this is
    only ever an approximation using the pre-slippage quoted price). Real market impact is convex
    in participation rate; omitting it (or a zero ``participation_impact_coefficient``, as in
    ``cost_model_v1``) reproduces the original flat-bps model exactly."""
    bps = params.slippage_bps
    if participation_fraction is not None and params.participation_impact_coefficient != 0:
        fraction = max(Decimal(0), min(participation_fraction, Decimal(1)))
        bps = bps * (1 + params.participation_impact_coefficient * fraction)
    adjustment = price * bps / Decimal(10_000)
    if direction == "buy":
        return price + adjustment
    return price - adjustment


def liquidity_cap(
    trailing_avg_volume_base: Decimal | None, price: Decimal, params: CostParameterSet
) -> Decimal | None:
    """The maximum notional a position may be sized at, given the TRAILING average volume through
    the decision day (never the execution bar's own, not-yet-known volume — see module docstring
    of ``cfi.backtest``). ``None`` means no cap could be computed (missing volume data — R3: this
    is a first-class state, the caller must not silently ignore it and size without limit)."""
    if trailing_avg_volume_base is None:
        return None
    return trailing_avg_volume_base * price * params.max_participation_pct / Decimal(100)

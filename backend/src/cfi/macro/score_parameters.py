"""Versioned parameter set for the Macro Environment Score (Phase 11).

Same rationale and pattern as the Liquidity Score's parameter registry
(``cfi/liquidity/score_parameters.py``, Phase 9) and every score before it: weights, reference
scales, minimum available weight and band boundaries are judgment parameters (R2: Calculated
Metric, not fitted to data), chosen by design and published alongside every score. They live in a
plain, append-only Python module, not a database table — there is exactly one active version at a
time and nothing here is edited at runtime. ``parameters()`` is the interface the scoring engine
depends on.

**Do not edit the values of an existing entry once it has been used to compute a score that
someone has seen.** Add a new ``ParameterSet`` under a new version id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParameterSet:
    """One complete, named set of Macro Environment Score parameters.

    Weights are expected to sum to 1 (checked by tests, not enforced at construction). Every
    "scale" is the metric value at which that component's sub-score reaches ±1 — see ``score.py``'s
    module docstring for the sub-score formula. A positive sub-score always means "more
    accommodative / risk-on"; a negative one "more restrictive / risk-off" — a description of the
    conventional macro backdrop, never a crypto-price direction (R1; the phase's explicit
    instruction not to convert macro data into deterministic crypto predictions).
    """

    version: str
    weight_yield_curve: Decimal
    weight_real_policy_rate: Decimal
    weight_vix: Decimal
    weight_equity_trend: Decimal
    weight_dollar_trend: Decimal
    weight_net_liquidity_trend: Decimal
    weight_oil_trend: Decimal
    yield_curve_scale: Decimal  # 10y-2y slope (pp) at which the sub-score reaches ±1
    real_policy_rate_scale: Decimal  # |real policy rate| (pp) at which the sub-score reaches ±1
    vix_reference: Decimal  # VIX level treated as neutral (long-run average)
    vix_scale: Decimal  # |VIX - reference| at which the sub-score reaches ±1
    equity_trend_scale: Decimal  # |90-day S&P 500 change| (ratio) at which the sub-score reaches ±1
    dollar_trend_scale: Decimal  # |90-day dollar-index-proxy change| at which sub-score reaches ±1
    net_liquidity_trend_scale: Decimal  # |90-day US net-liquidity change| at ± 1
    oil_trend_scale: Decimal  # |90-day WTI change| at which the sub-score reaches ±1
    min_available_weight: Decimal  # below this available weight, score is "Insufficient data"
    bands: tuple[tuple[Decimal | None, str], ...]  # (lower bound or None, label); highest first


MACRO_SCORE_V1 = ParameterSet(
    version="macro_score_v1",
    weight_yield_curve=Decimal("0.20"),
    weight_real_policy_rate=Decimal("0.20"),
    weight_vix=Decimal("0.15"),
    weight_equity_trend=Decimal("0.15"),
    weight_dollar_trend=Decimal("0.10"),
    weight_net_liquidity_trend=Decimal("0.15"),
    weight_oil_trend=Decimal("0.05"),
    yield_curve_scale=Decimal("1.00"),
    real_policy_rate_scale=Decimal("2.00"),
    vix_reference=Decimal(20),
    vix_scale=Decimal(10),
    equity_trend_scale=Decimal("0.10"),
    dollar_trend_scale=Decimal("0.05"),
    net_liquidity_trend_scale=Decimal("0.05"),
    oil_trend_scale=Decimal("0.15"),
    min_available_weight=Decimal("0.5"),
    bands=(
        (Decimal(50), "broadly accommodative macro backdrop"),
        (Decimal(15), "improving macro backdrop"),
        (Decimal(-15), "neutral / mixed macro backdrop"),
        (Decimal(-50), "tightening macro backdrop"),
        (None, "broadly restrictive macro backdrop"),
    ),
)

#: Every parameter set ever published, keyed by version id. Append-only: never replace an
#: existing entry's values (see module docstring).
PARAMETER_SETS: dict[str, ParameterSet] = {MACRO_SCORE_V1.version: MACRO_SCORE_V1}

#: The version the scoring engine uses when none is specified.
CURRENT_VERSION = MACRO_SCORE_V1.version


def parameters(version: str | None = None) -> ParameterSet:
    """Look up a named parameter set (defaults to :data:`CURRENT_VERSION`).

    An unknown version id is a hard error rather than a silent fallback (R3): a caller asking for a
    specific historical version must get that version or an explicit failure, never a substitute
    it did not ask for.
    """
    key = version or CURRENT_VERSION
    if key not in PARAMETER_SETS:
        raise KeyError(f"Unknown Macro Environment Score parameter version: {key!r}")
    return PARAMETER_SETS[key]

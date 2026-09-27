"""Versioned parameter set for the Market Structure Score (Phase 12).

Same rationale and pattern as every score's parameter registry before it (Liquidity Score
``cfi/liquidity/score_parameters.py``, Retail Score, Macro Environment Score
``cfi/macro/score_parameters.py``): weights, reference scales, minimum available weight and band
boundaries are judgment parameters (R2: Calculated Metric, not fitted to data), chosen by design and
published alongside every score. They live in a plain, append-only Python module, not a database
table — there is exactly one active version at a time and nothing here is edited at runtime.
``parameters()`` is the interface the scoring engine depends on.

**Do not edit the values of an existing entry once it has been used to compute a score that someone
has seen.** Add a new ``ParameterSet`` under a new version id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParameterSet:
    """One complete, named set of Market Structure Score parameters.

    Weights are expected to sum to 1 (checked by tests, not enforced at construction). Every
    "scale" is the metric value at which that component's sub-score reaches ±1 — see ``score.py``'s
    module docstring for the sub-score formula. A positive sub-score always means "stronger /
    more constructive technical structure"; a negative one "weaker / more deteriorated technical
    structure" — a description of the current technical condition of already-tracked price and
    market-cap data, never a trading signal or recommendation (this phase's explicit instruction).
    """

    version: str
    weight_price_trend: Decimal
    weight_momentum: Decimal
    weight_breadth: Decimal
    weight_altcoin_relative_strength: Decimal
    weight_volatility_regime: Decimal
    price_trend_scale: Decimal  # |BTC close/SMA200 - 1| at which the sub-score reaches +/-1
    momentum_scale: Decimal  # |BTC RSI - 50| at which the sub-score reaches +/-1
    breadth_scale: Decimal  # |breadth fraction - 0.5| at which the sub-score reaches +/-1
    altcoin_relative_strength_scale: Decimal  # |avg spread_pp vs BTC| at which sub-score is +/-1
    volatility_regime_scale: Decimal  # |vol. percentile - 50| at which sub-score reaches +/-1
    min_available_weight: Decimal  # below this available weight, score is "Insufficient data"
    bands: tuple[tuple[Decimal | None, str], ...]  # (lower bound or None, label); highest first


MARKET_STRUCTURE_SCORE_V1 = ParameterSet(
    version="market_structure_score_v1",
    weight_price_trend=Decimal("0.25"),
    weight_momentum=Decimal("0.20"),
    weight_breadth=Decimal("0.20"),
    weight_altcoin_relative_strength=Decimal("0.20"),
    weight_volatility_regime=Decimal("0.15"),
    price_trend_scale=Decimal("0.20"),
    momentum_scale=Decimal(50),
    breadth_scale=Decimal("0.50"),
    altcoin_relative_strength_scale=Decimal("0.15"),
    volatility_regime_scale=Decimal(50),
    min_available_weight=Decimal("0.5"),
    bands=(
        (Decimal(50), "broadly constructive technical structure"),
        (Decimal(15), "improving technical structure"),
        (Decimal(-15), "neutral / mixed technical structure"),
        (Decimal(-50), "deteriorating technical structure"),
        (None, "broadly weak technical structure"),
    ),
)

#: Every parameter set ever published, keyed by version id. Append-only: never replace an
#: existing entry's values (see module docstring).
PARAMETER_SETS: dict[str, ParameterSet] = {
    MARKET_STRUCTURE_SCORE_V1.version: MARKET_STRUCTURE_SCORE_V1
}

#: The version the scoring engine uses when none is specified.
CURRENT_VERSION = MARKET_STRUCTURE_SCORE_V1.version


def parameters(version: str | None = None) -> ParameterSet:
    """Look up a named parameter set (defaults to :data:`CURRENT_VERSION`).

    An unknown version id is a hard error rather than a silent fallback (R3): a caller asking for a
    specific historical version must get that version or an explicit failure, never a substitute it
    did not ask for.
    """
    key = version or CURRENT_VERSION
    if key not in PARAMETER_SETS:
        raise KeyError(f"Unknown Market Structure Score parameter version: {key!r}")
    return PARAMETER_SETS[key]

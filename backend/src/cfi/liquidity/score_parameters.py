"""Versioned parameter set for the Liquidity Score (Phase 9).

Same rationale and pattern as the Derivatives Health Score's parameter registry
(``cfi/derivatives/score_parameters.py``, Phase 8 addendum), reused here from the start rather
than bolted on afterwards: weights, reference scales, minimum available weight and band
boundaries are judgment parameters (R2: Calculated Metric, not fitted to data), chosen by
design and published alongside every score. They live in a plain, append-only Python module,
not a database table — there is exactly one active version at a time and nothing here is
edited at runtime. ``parameters()`` is the interface the scoring engine depends on.

**Do not edit the values of an existing entry once it has been used to compute a score that
someone has seen.** Add a new ``ParameterSet`` under a new version id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParameterSet:
    """One complete, named set of Liquidity Score parameters.

    Weights are expected to sum to 1 (checked by tests, not enforced at construction). Every
    "scale" is the metric value (a ratio, e.g. 0.05 = 5 %) at which that component's sub-score
    reaches ±1 — see ``score.py``'s module docstring for the sub-score formula.
    """

    version: str
    weight_usdt_growth_7d: Decimal
    weight_usdc_growth_7d: Decimal
    weight_total_growth_7d: Decimal
    weight_acceleration: Decimal
    usdt_growth_scale: Decimal  # 7-day USDT supply growth ratio at which sub-score reaches ±1
    usdc_growth_scale: Decimal  # 7-day USDC supply growth ratio at which sub-score reaches ±1
    total_growth_scale: Decimal  # 7-day total stablecoin supply growth ratio, same meaning
    acceleration_scale: Decimal  # |change in the 7-day growth rate| at which sub-score reaches ±1
    min_available_weight: Decimal  # below this available weight, score is "Insufficient data"
    bands: tuple[tuple[Decimal | None, str], ...]  # (lower bound or None, label); highest first


LIQUIDITY_SCORE_V1 = ParameterSet(
    version="liquidity_score_v1",
    weight_usdt_growth_7d=Decimal("0.30"),
    weight_usdc_growth_7d=Decimal("0.30"),
    weight_total_growth_7d=Decimal("0.25"),
    weight_acceleration=Decimal("0.15"),
    usdt_growth_scale=Decimal("0.05"),
    usdc_growth_scale=Decimal("0.05"),
    total_growth_scale=Decimal("0.04"),
    acceleration_scale=Decimal("0.03"),
    min_available_weight=Decimal("0.5"),
    bands=(
        (Decimal(50), "strong liquidity expansion"),
        (Decimal(15), "liquidity expansion"),
        (Decimal(-15), "stable"),
        (Decimal(-50), "liquidity contraction"),
        (None, "strong liquidity contraction"),
    ),
)

#: Every parameter set ever published, keyed by version id. Append-only: never replace an
#: existing entry's values (see module docstring).
PARAMETER_SETS: dict[str, ParameterSet] = {LIQUIDITY_SCORE_V1.version: LIQUIDITY_SCORE_V1}

#: The version the scoring engine uses when none is specified.
CURRENT_VERSION = LIQUIDITY_SCORE_V1.version


def parameters(version: str | None = None) -> ParameterSet:
    """Look up a named parameter set (defaults to :data:`CURRENT_VERSION`).

    An unknown version id is a hard error rather than a silent fallback (R3): a caller asking
    for a specific historical version must get that version or an explicit failure, never a
    substitute it did not ask for.
    """
    key = version or CURRENT_VERSION
    if key not in PARAMETER_SETS:
        raise KeyError(f"Unknown Liquidity Score parameter version: {key!r}")
    return PARAMETER_SETS[key]

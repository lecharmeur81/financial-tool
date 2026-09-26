"""Versioned parameter sets for the two Phase 10 scores (Retail Activity Score, Retail Speculation
Score). Same rationale as the Derivatives Health Score / Liquidity Score registries: weights,
reference scales and band boundaries are judgment parameters (R2: Calculated Metric, not fitted to
data), chosen by design and published alongside every score, in a plain append-only Python module.

**Do not edit the values of an existing entry once it has been used to compute a score that
someone has seen.** Add a new entry under a new version id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ActivityParameterSet:
    """Retail Activity Score: unsigned 0-100. Every component is already a 0-100 historical
    percentile (``retail/metrics.py::percentile_rank``); weights combine them directly — there is
    no reference scale (a percentile is already on a 0-100 scale)."""

    version: str
    weight_small_tx_percentile: Decimal
    weight_meme_trending_percentile: Decimal
    weight_derivatives_turnover_percentile: Decimal
    min_available_weight: Decimal
    bands: tuple[tuple[Decimal | None, str], ...]  # (lower bound or None, label); highest first


@dataclass(frozen=True, slots=True)
class SpeculationParameterSet:
    """Retail Speculation Score: signed -100..+100. Each "scale" is the metric value at which
    that component's sub-score reaches +-1 (see score.py's module docstring for the formula).
    ``meme_trending`` is documented as an unsigned, always->=0 contributor (see score.py)."""

    version: str
    weight_funding_rate_bias: Decimal
    weight_account_ratio_skew: Decimal
    weight_meme_trending: Decimal
    funding_rate_scale: Decimal
    account_ratio_skew_scale: Decimal
    meme_trending_scale: Decimal  # count of curated meme coins trending at which sub-score = +1
    min_available_weight: Decimal
    bands: tuple[tuple[Decimal | None, str], ...]


RETAIL_ACTIVITY_SCORE_V1 = ActivityParameterSet(
    version="retail_activity_score_v1",
    weight_small_tx_percentile=Decimal("0.35"),
    weight_meme_trending_percentile=Decimal("0.30"),
    weight_derivatives_turnover_percentile=Decimal("0.35"),
    min_available_weight=Decimal("0.5"),
    bands=(
        (Decimal(80), "elevated retail-proxy activity"),
        (Decimal(60), "above-normal retail-proxy activity"),
        (Decimal(40), "typical retail-proxy activity"),
        (Decimal(20), "below-normal retail-proxy activity"),
        (None, "quiet retail-proxy activity"),
    ),
)

RETAIL_SPECULATION_SCORE_V1 = SpeculationParameterSet(
    version="retail_speculation_score_v1",
    weight_funding_rate_bias=Decimal("0.40"),
    weight_account_ratio_skew=Decimal("0.40"),
    weight_meme_trending=Decimal("0.20"),
    funding_rate_scale=Decimal("0.0005"),
    account_ratio_skew_scale=Decimal("0.5"),
    meme_trending_scale=Decimal(2),
    min_available_weight=Decimal("0.4"),
    bands=(
        (Decimal(50), "strong long-biased speculative skew"),
        (Decimal(15), "long-biased speculative skew"),
        (Decimal(-15), "balanced"),
        (Decimal(-50), "short-biased speculative skew"),
        (None, "strong short-biased speculative skew"),
    ),
)

ACTIVITY_PARAMETER_SETS: dict[str, ActivityParameterSet] = {
    RETAIL_ACTIVITY_SCORE_V1.version: RETAIL_ACTIVITY_SCORE_V1
}
SPECULATION_PARAMETER_SETS: dict[str, SpeculationParameterSet] = {
    RETAIL_SPECULATION_SCORE_V1.version: RETAIL_SPECULATION_SCORE_V1
}

CURRENT_ACTIVITY_VERSION = RETAIL_ACTIVITY_SCORE_V1.version
CURRENT_SPECULATION_VERSION = RETAIL_SPECULATION_SCORE_V1.version


def activity_parameters(version: str | None = None) -> ActivityParameterSet:
    key = version or CURRENT_ACTIVITY_VERSION
    if key not in ACTIVITY_PARAMETER_SETS:
        raise KeyError(f"Unknown Retail Activity Score parameter version: {key!r}")
    return ACTIVITY_PARAMETER_SETS[key]


def speculation_parameters(version: str | None = None) -> SpeculationParameterSet:
    key = version or CURRENT_SPECULATION_VERSION
    if key not in SPECULATION_PARAMETER_SETS:
        raise KeyError(f"Unknown Retail Speculation Score parameter version: {key!r}")
    return SPECULATION_PARAMETER_SETS[key]

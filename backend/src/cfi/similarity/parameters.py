"""Versioned feature/normalization parameters for the Historical Similarity Engine (Phase 15).

Same convention as every other score in this platform (``cfi.market_structure.score_parameters``,
``cfi.regime.parameters``, etc.): frozen dataclasses, an append-only ``PARAMETER_SETS`` registry,
and a ``parameters(version)`` accessor that raises a hard ``KeyError`` on an unknown version rather
than silently falling back (R3). Do not edit the values of an existing entry once it has been used
to compute a similarity score someone has seen — add a new version instead.

Each feature's normalization bounds are **fixed constants, decided once, independent of any date's
own data** (ADR-0058) — never derived from a trailing window or from the candidate set being
searched. This is a deliberate design choice, not an oversight: deriving normalization scale from
data would make every candidate's similarity score sensitive to which OTHER dates happen to be in
the search batch (including dates after that candidate), which is exactly the kind of indirect
look-ahead leakage this phase's explicit instruction ("never allow future information to influence
the similarity score") rules out. Five of the nine features are already-published composite scores
on a fixed, documented range of their own (each domain's own ``score.py`` docstring: range
"-100 ... +100"); the remaining four use fixed clamp bounds chosen as generous, documented, v1
judgment values — not fitted to data — awaiting the user's review, same posture as every score
band in this platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Normalization = Literal["identity_0_100", "shift_pm100_to_0_100", "clamp_linear"]


@dataclass(frozen=True, slots=True)
class FeatureDef:
    feature_id: str
    label: str
    weight: Decimal
    normalization: Normalization
    unit: str
    evidence: str
    clamp_min: Decimal | None = None
    clamp_max: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ParameterSet:
    version: str
    features: tuple[FeatureDef, ...]
    min_available_weight: Decimal
    lookback_days: int
    step_days: int
    min_candidate_age_days: int
    min_gap_days: int
    top_n_analogues: int
    max_distribution_sample: int
    min_distribution_sample: int
    forward_return_horizons_days: tuple[int, ...]
    drawdown_window_days: int


_SIMILARITY_V1_FEATURES: tuple[FeatureDef, ...] = (
    FeatureDef(
        "institutional_score",
        "Institutional flow score",
        Decimal("0.15"),
        "shift_pm100_to_0_100",
        unit="score (-100..100)",
        evidence="cfi.institutional.service.InstitutionalService.score() — already a Calculated "
        "Metric on a fixed, documented -100..100 range.",
    ),
    FeatureDef(
        "whale_score",
        "Whale flow score",
        Decimal("0.15"),
        "shift_pm100_to_0_100",
        unit="score (-100..100)",
        evidence="cfi.whales.service.WhaleService.score() — fixed, documented -100..100 range.",
    ),
    FeatureDef(
        "retail_activity_score",
        "Retail activity score",
        Decimal("0.10"),
        "identity_0_100",
        unit="score (0..100)",
        evidence="cfi.retail.service.RetailService.overview()['activity_score'] — fixed, "
        "documented 0..100 range.",
    ),
    FeatureDef(
        "liquidity_score",
        "Liquidity score",
        Decimal("0.10"),
        "shift_pm100_to_0_100",
        unit="score (-100..100)",
        evidence="cfi.liquidity.service.LiquidityService.overview()['score'] — fixed, documented "
        "-100..100 range.",
    ),
    FeatureDef(
        "funding_annualised_7d_pct",
        "Perpetual funding rate (annualised, 7-day)",
        Decimal("0.10"),
        "clamp_linear",
        unit="% annualised",
        evidence="cfi.derivatives.service.DerivativesService.asset()['funding']"
        "['annualised_7d_pct'] — a raw, standalone rate, not a composite score; clamped to a "
        "fixed, documented range covering realistic historical extremes.",
        clamp_min=Decimal("-100"),
        clamp_max=Decimal("100"),
    ),
    FeatureDef(
        "oi_change_7d_pct",
        "Open interest, 7-day change",
        Decimal("0.10"),
        "clamp_linear",
        unit="% change",
        evidence="cfi.derivatives.service.DerivativesService.asset()['open_interest']"
        "['change_7d_pct'] — a raw, standalone change, not a composite score; clamped to a fixed, "
        "documented range.",
        clamp_min=Decimal("-50"),
        clamp_max=Decimal("50"),
    ),
    FeatureDef(
        "volatility_percentile",
        "Realized volatility percentile",
        Decimal("0.10"),
        "identity_0_100",
        unit="percentile (0..100)",
        evidence="cfi.market_structure.service.MarketStructureService.overview()"
        "['assets']['BTC']['volatility']['percentile'] — already a percentile against BTC's own "
        "trailing history.",
    ),
    FeatureDef(
        "market_structure_score",
        "Market structure score",
        Decimal("0.10"),
        "shift_pm100_to_0_100",
        unit="score (-100..100)",
        evidence="cfi.market_structure.service.MarketStructureService.overview()['score'] — "
        "fixed, documented -100..100 range.",
    ),
    FeatureDef(
        "macro_score",
        "Macro score",
        Decimal("0.10"),
        "shift_pm100_to_0_100",
        unit="score (-100..100)",
        evidence="cfi.macro.service.MacroService.overview()['score'] — fixed, documented "
        "-100..100 range.",
    ),
)

SIMILARITY_CLASSIFIER_V1 = ParameterSet(
    version="similarity_v1",
    features=_SIMILARITY_V1_FEATURES,
    min_available_weight=Decimal("0.5"),
    lookback_days=730,
    step_days=7,
    min_candidate_age_days=14,
    min_gap_days=30,
    top_n_analogues=5,
    max_distribution_sample=15,
    min_distribution_sample=3,
    forward_return_horizons_days=(7, 30, 90),
    drawdown_window_days=90,
)

PARAMETER_SETS: dict[str, ParameterSet] = {"similarity_v1": SIMILARITY_CLASSIFIER_V1}
CURRENT_VERSION = "similarity_v1"


def parameters(version: str | None = None) -> ParameterSet:
    v = version or CURRENT_VERSION
    if v not in PARAMETER_SETS:
        raise KeyError(f"unknown similarity parameter version: {v!r}")
    return PARAMETER_SETS[v]


def normalize(value: Decimal, feature: FeatureDef) -> Decimal:
    """Map a raw feature value onto a common 0..100 scale using this feature's own fixed,
    documented bounds — never data-derived (see module docstring)."""
    if feature.normalization == "identity_0_100":
        return value
    if feature.normalization == "shift_pm100_to_0_100":
        return (value + Decimal(100)) / 2
    if feature.normalization == "clamp_linear":
        assert feature.clamp_min is not None  # noqa: S101
        assert feature.clamp_max is not None  # noqa: S101
        lo, hi = feature.clamp_min, feature.clamp_max
        clamped = max(lo, min(hi, value))
        return (clamped - lo) / (hi - lo) * 100
    raise ValueError(f"unknown normalization method: {feature.normalization!r}")  # pragma: no cover

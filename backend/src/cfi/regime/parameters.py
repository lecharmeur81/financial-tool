"""Versioned regime-classification parameters (Phase 14).

Follows the same versioned-parameter-set convention as every score in this platform
(``cfi.derivatives.score_parameters``, ``cfi.market_structure.score_parameters``, etc.): a frozen,
immutable registry, an append-only ``PARAMETER_SETS`` dict, and :func:`parameters` raising a hard
``KeyError`` on an unknown version id rather than silently falling back (R3).

Each of the six substantive regimes (``mixed_unclear`` is the classifier's own fallback, never
itself defined here — see ``cfi.regime.classifier``) is a named set of single-metric conditions,
each carrying a weight; weights within one regime sum to 1. Thresholds are anchored, wherever
sensible, to the *same* numeric bands each underlying domain score already publishes (e.g. the
+-15/+-50 "net inflow / strong net inflow" bands used by the institutional, whale, liquidity and
macro scores; the 70/30 RSI overbought/oversold levels; the 75%/25% market-breadth thresholds) —
documented reuse for consistency, not a fabricated new scale. Like every score's parameters, this
is a v1 judgment methodology: chosen by design, not fitted to data or empirically validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Comparator = Literal["gte", "lte", "between", "categorical"]


@dataclass(frozen=True, slots=True)
class ConditionDef:
    """One single-metric test contributing to one regime's confidence.

    ``metric_key`` must be a key produced by ``cfi.regime.snapshot.gather_snapshot``.
    ``comparator="between"`` matches when ``threshold <= value <= threshold_high``.
    ``comparator="categorical"`` matches when the metric's ``condition`` string is a member of
    ``expected`` (e.g. ``btc_trend`` being one of ``("downtrend", "mixed")``).
    """

    condition_id: str
    label: str
    metric_key: str
    comparator: Comparator
    weight: Decimal
    rationale: str
    threshold: Decimal | None = None
    threshold_high: Decimal | None = None
    expected: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class RegimeDefinition:
    regime_id: str
    label: str
    description: str
    conditions: tuple[ConditionDef, ...]


@dataclass(frozen=True, slots=True)
class ParameterSet:
    version: str
    regimes: tuple[RegimeDefinition, ...]
    min_available_weight: Decimal
    min_confidence_assign: Decimal
    tie_margin: Decimal
    # ADR-0062 (Phase 18, RED_TEAM_REPORT.md finding #4): a previously-assigned regime is only
    # abandoned for a new top-scoring regime once the challenger beats it by MORE than this
    # margin — a dead-zone/hysteresis band, not a strict "highest confidence always wins" rule.
    # Zero (regime_classifier_v1's value) reproduces the original flip-on-any-margin behavior
    # exactly. See ``cfi.regime.classifier.classify``'s ``previous_regime_id`` parameter.
    hysteresis_margin: Decimal = Decimal("0")


_ACCUMULATION = RegimeDefinition(
    regime_id="accumulation",
    label="Accumulation",
    description=(
        "Smart money appears to be quietly building positions while price has stabilised after a "
        "decline and retail participation stays subdued."
    ),
    conditions=(
        ConditionDef(
            "ms_not_uptrend",
            "Market Structure Score not yet in a clear uptrend",
            "market_structure_score",
            "lte",
            Decimal("0.15"),
            "Accumulation precedes a confirmed uptrend, it does not follow one.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "btc_trend_down_or_mixed",
            "BTC price trend is downtrend or mixed, not yet an uptrend",
            "btc_trend",
            "categorical",
            Decimal("0.10"),
            "Same reasoning as the Market Structure Score condition above, at the trend level.",
            expected=("downtrend", "mixed"),
        ),
        ConditionDef(
            "whale_accumulating",
            "Whale Flow Score at or above the 'accumulation' band",
            "whale_score",
            "gte",
            Decimal("0.25"),
            "The core signal: on-chain whale behaviour showing net accumulation.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "institutional_non_negative",
            "Institutional Flow Score is non-negative (not net outflow)",
            "institutional_score",
            "gte",
            Decimal("0.15"),
            "Institutions are not actively distributing during the build-up.",
            threshold=Decimal(0),
        ),
        ConditionDef(
            "retail_quiet",
            "Retail Activity Score at or below 'typical' (below-normal or quiet)",
            "retail_activity_score",
            "lte",
            Decimal("0.20"),
            "Retail is disinterested — the defining contrast of accumulation.",
            threshold=Decimal(40),
        ),
        ConditionDef(
            "derivatives_calm",
            "Derivatives Health at or above 'moderate stress' (i.e. not stressed)",
            "derivatives_health",
            "gte",
            Decimal("0.15"),
            "Leverage is not extreme; no forced-selling pressure building.",
            threshold=Decimal(50),
        ),
    ),
)

_RECOVERY = RegimeDefinition(
    regime_id="recovery",
    label="Recovery",
    description=(
        "An early uptrend is forming, confirmed by both institutional and whale flow, while "
        "retail participation is still modest."
    ),
    conditions=(
        ConditionDef(
            "ms_improving",
            "Market Structure Score improving but not yet 'broadly constructive'",
            "market_structure_score",
            "between",
            Decimal("0.15"),
            "Recovery is the transition band between neutral and broadly constructive.",
            threshold=Decimal(-15),
            threshold_high=Decimal(50),
        ),
        ConditionDef(
            "btc_uptrend",
            "BTC price trend has turned to uptrend",
            "btc_trend",
            "categorical",
            Decimal("0.15"),
            "A structural (SMA-ordering) confirmation of the turn.",
            expected=("uptrend",),
        ),
        ConditionDef(
            "btc_rsi_recovering",
            "BTC RSI(14) between 45 and 70 — rising momentum, not yet overbought",
            "btc_rsi",
            "between",
            Decimal("0.10"),
            "Momentum turning up without already being stretched.",
            threshold=Decimal(45),
            threshold_high=Decimal(70),
        ),
        ConditionDef(
            "whale_accumulating",
            "Whale Flow Score at or above the 'accumulation' band",
            "whale_score",
            "gte",
            Decimal("0.20"),
            "Whale accumulation continuing into the turn.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "institutional_inflow",
            "Institutional Flow Score at or above the 'net inflow' band",
            "institutional_score",
            "gte",
            Decimal("0.20"),
            "Institutions confirming the turn with net inflow.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "retail_not_yet_elevated",
            "Retail Activity Score at or below 'above-normal'",
            "retail_activity_score",
            "lte",
            Decimal("0.10"),
            "Retail has not yet chased the move.",
            threshold=Decimal(60),
        ),
        ConditionDef(
            "liquidity_stable_or_expanding",
            "Liquidity Score at or above 'stable'",
            "liquidity_score",
            "gte",
            Decimal("0.10"),
            "Dry powder is not contracting during the recovery.",
            threshold=Decimal(-15),
        ),
    ),
)

_EXPANSION = RegimeDefinition(
    regime_id="expansion",
    label="Expansion",
    description=(
        "A broad-based uptrend: price, market breadth and institutional flow all confirming, "
        "leverage building but still within a healthy range."
    ),
    conditions=(
        ConditionDef(
            "ms_constructive",
            "Market Structure Score at or above 'improving'",
            "market_structure_score",
            "gte",
            Decimal("0.20"),
            "A confirmed, not merely emerging, constructive structure.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "btc_uptrend",
            "BTC price trend is an uptrend",
            "btc_trend",
            "categorical",
            Decimal("0.10"),
            "Structural confirmation of the trend.",
            expected=("uptrend",),
        ),
        ConditionDef(
            "btc_rsi_healthy",
            "BTC RSI(14) between 50 and 70 — firm momentum, not yet overbought",
            "btc_rsi",
            "between",
            Decimal("0.10"),
            "Momentum supportive without being stretched into euphoria.",
            threshold=Decimal(50),
            threshold_high=Decimal(70),
        ),
        ConditionDef(
            "breadth_advancing",
            "Market breadth is 'broad_advance'",
            "market_breadth",
            "categorical",
            Decimal("0.15"),
            "The move is broad-based across the tracked universe, not BTC alone.",
            expected=("broad_advance",),
        ),
        ConditionDef(
            "institutional_inflow",
            "Institutional Flow Score at or above 'net inflow'",
            "institutional_score",
            "gte",
            Decimal("0.15"),
            "Institutional flow continuing to confirm the expansion.",
            threshold=Decimal(15),
        ),
        ConditionDef(
            "retail_participating_not_extreme",
            "Retail Activity Score between 'typical' and 'elevated' (40-80)",
            "retail_activity_score",
            "between",
            Decimal("0.10"),
            "Retail is participating, but not yet at an extreme.",
            threshold=Decimal(40),
            threshold_high=Decimal(80),
        ),
        ConditionDef(
            "derivatives_healthy",
            "Derivatives Health at or above 'moderate stress'",
            "derivatives_health",
            "gte",
            Decimal("0.10"),
            "Leverage building alongside the trend, not yet stressed.",
            threshold=Decimal(50),
        ),
        ConditionDef(
            "liquidity_expanding",
            "Liquidity Score at or above 'expansion'",
            "liquidity_score",
            "gte",
            Decimal("0.10"),
            "Dry powder (stablecoin supply) is expanding alongside the move.",
            threshold=Decimal(15),
        ),
    ),
)

_EUPHORIA = RegimeDefinition(
    regime_id="euphoria",
    label="Euphoria",
    description=(
        "Parabolic price action with retail chasing, speculative leverage extreme, and structure "
        "overheated — the classic late-cycle warning signs."
    ),
    conditions=(
        ConditionDef(
            "ms_broadly_constructive",
            "Market Structure Score at or above 'broadly constructive'",
            "market_structure_score",
            "gte",
            Decimal("0.10"),
            "Structure has been strongly constructive for some time.",
            threshold=Decimal(50),
        ),
        ConditionDef(
            "btc_overbought",
            "BTC RSI(14) at or above 70 (overbought)",
            "btc_rsi",
            "gte",
            Decimal("0.20"),
            "Momentum stretched to an overbought extreme.",
            threshold=Decimal(70),
        ),
        ConditionDef(
            "retail_elevated",
            "Retail Activity Score at or above 'elevated'",
            "retail_activity_score",
            "gte",
            Decimal("0.20"),
            "Retail attention/participation at its own historical extreme.",
            threshold=Decimal(80),
        ),
        ConditionDef(
            "retail_long_biased",
            "Retail Speculation Score at or above 'strong long-biased'",
            "retail_speculation_score",
            "gte",
            Decimal("0.15"),
            "Speculative positioning is one-sidedly long.",
            threshold=Decimal(50),
        ),
        ConditionDef(
            "derivatives_stressed",
            "Derivatives Health at or below 'moderate stress' (i.e. already stressed)",
            "derivatives_health",
            "lte",
            Decimal("0.20"),
            "Leverage/funding extremes typical of a euphoric top.",
            threshold=Decimal(50),
        ),
        ConditionDef(
            "volatility_elevated",
            "BTC realized-volatility percentile at or above 80 (elevated)",
            "btc_volatility_percentile",
            "gte",
            Decimal("0.15"),
            "Price action itself has become unusually volatile.",
            threshold=Decimal(80),
        ),
    ),
)

_DISTRIBUTION = RegimeDefinition(
    regime_id="distribution",
    label="Distribution",
    description=(
        "Smart money appears to be exiting while retail remains enthusiastic and momentum is "
        "quietly weakening beneath the surface."
    ),
    conditions=(
        ConditionDef(
            "btc_rsi_weakening",
            "BTC RSI(14) between 40 and 70 — off an overbought extreme, not yet oversold",
            "btc_rsi",
            "between",
            Decimal("0.15"),
            "Momentum has come off its highs without yet breaking down.",
            threshold=Decimal(40),
            threshold_high=Decimal(70),
        ),
        ConditionDef(
            "institutional_outflow",
            "Institutional Flow Score at or below 'net outflow'",
            "institutional_score",
            "lte",
            Decimal("0.25"),
            "The core signal: institutions net selling/redeeming.",
            threshold=Decimal(-15),
        ),
        ConditionDef(
            "whale_distributing",
            "Whale Flow Score at or below 'distribution'",
            "whale_score",
            "lte",
            Decimal("0.20"),
            "On-chain whale behaviour showing net distribution.",
            threshold=Decimal(-15),
        ),
        ConditionDef(
            "retail_still_elevated",
            "Retail Activity Score at or above 'above-normal'",
            "retail_activity_score",
            "gte",
            Decimal("0.20"),
            "Retail is still buying while smart money exits — the defining contrast.",
            threshold=Decimal(60),
        ),
        ConditionDef(
            "derivatives_stressed",
            "Derivatives Health at or below 'moderate stress'",
            "derivatives_health",
            "lte",
            Decimal("0.20"),
            "Leverage stress building as the top forms.",
            threshold=Decimal(50),
        ),
    ),
)

_CAPITULATION = RegimeDefinition(
    regime_id="capitulation",
    label="Capitulation",
    description=(
        "Sharp, forced selling: extreme derivatives stress, elevated volatility, a confirmed "
        "downtrend and a risk-off macro backdrop."
    ),
    conditions=(
        ConditionDef(
            "btc_downtrend",
            "BTC price trend is a downtrend",
            "btc_trend",
            "categorical",
            Decimal("0.15"),
            "Structural confirmation of the decline.",
            expected=("downtrend",),
        ),
        ConditionDef(
            "btc_oversold",
            "BTC RSI(14) at or below 30 (oversold)",
            "btc_rsi",
            "lte",
            Decimal("0.15"),
            "Momentum at a washed-out extreme.",
            threshold=Decimal(30),
        ),
        ConditionDef(
            "ms_broadly_weak",
            "Market Structure Score at or below 'broadly weak'",
            "market_structure_score",
            "lte",
            Decimal("0.15"),
            "Structure has deteriorated to its own most severe band.",
            threshold=Decimal(-50),
        ),
        ConditionDef(
            "derivatives_high_stress",
            "Derivatives Health at or below 'elevated stress' (i.e. high stress)",
            "derivatives_health",
            "lte",
            Decimal("0.20"),
            "Leverage/funding at an extreme, forced-liquidation-prone level.",
            threshold=Decimal(25),
        ),
        ConditionDef(
            "liquidation_event_active",
            "A recent derivatives liquidation event is flagged active",
            "derivatives_liquidation_event",
            "categorical",
            Decimal("0.10"),
            "A directly observed forced-deleveraging event, not just an inferred one.",
            expected=("active",),
        ),
        ConditionDef(
            "volatility_elevated",
            "BTC realized-volatility percentile at or above 80 (elevated)",
            "btc_volatility_percentile",
            "gte",
            Decimal("0.15"),
            "Price action itself is unusually volatile, typical of a capitulation event.",
            threshold=Decimal(80),
        ),
        ConditionDef(
            "macro_restrictive",
            "Macro Environment Score at or below 'restrictive'",
            "macro_score",
            "lte",
            Decimal("0.10"),
            "A risk-off macro backdrop compounding the decline.",
            threshold=Decimal(-15),
        ),
    ),
)

REGIME_CLASSIFIER_V1 = ParameterSet(
    version="regime_classifier_v1",
    regimes=(
        _ACCUMULATION,
        _RECOVERY,
        _EXPANSION,
        _EUPHORIA,
        _DISTRIBUTION,
        _CAPITULATION,
    ),
    min_available_weight=Decimal("0.5"),
    min_confidence_assign=Decimal("0.55"),
    tie_margin=Decimal("0.08"),
    hysteresis_margin=Decimal("0"),  # preserved: v1 is deliberately flip-on-any-margin
)

REGIME_CLASSIFIER_V2 = ParameterSet(
    version="regime_classifier_v2",
    regimes=REGIME_CLASSIFIER_V1.regimes,
    min_available_weight=REGIME_CLASSIFIER_V1.min_available_weight,
    min_confidence_assign=REGIME_CLASSIFIER_V1.min_confidence_assign,
    tie_margin=REGIME_CLASSIFIER_V1.tie_margin,
    # A previously-assigned regime is kept unless a challenger beats it by more than 5
    # confidence points — damps the "14.99 <-> 15.01" single-day threshold oscillation finding #4
    # identified, without hiding a genuine, larger regime change. A documented judgment-call
    # magnitude (same posture as every other band in this platform), not fitted to data.
    hysteresis_margin=Decimal("0.05"),
)

#: Every parameter set ever published, keyed by version id. Append-only (see module docstring).
PARAMETER_SETS: dict[str, ParameterSet] = {
    REGIME_CLASSIFIER_V1.version: REGIME_CLASSIFIER_V1,
    REGIME_CLASSIFIER_V2.version: REGIME_CLASSIFIER_V2,
}

CURRENT_VERSION = REGIME_CLASSIFIER_V2.version


def parameters(version: str | None = None) -> ParameterSet:
    """Look up a published parameter set. An unknown version id is a hard error rather than a
    silent fallback (R3)."""
    key = version or CURRENT_VERSION
    try:
        return PARAMETER_SETS[key]
    except KeyError:
        raise KeyError(f"Unknown regime classifier parameter version: {key!r}") from None

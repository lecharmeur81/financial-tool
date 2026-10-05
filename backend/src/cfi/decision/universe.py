"""Versions, closed vocabularies and v0 judgment parameters for L4.5 Evidence Synthesis.

Authoritative source: ``METHODOLOGY_DECISION_INTELLIGENCE.md`` (Phase 38.1) and ADR-0076. Nothing
here is fitted to data: every threshold and mapping is a **v0 design judgment parameter, not an
empirically validated market predictor**. Changing any of them requires a new
``parameter_version``; changing template wording requires a new ``template_version``; an
output-changing fix requires a new ``methodology_version`` patch identifier.

``template_version`` is provenance metadata only. Assessment identity (for a future persistence
layer, not created here) is ``(snapshot_id, scope, methodology_version, parameter_version)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

METHODOLOGY_VERSION: Final = "decision_methodology.v0"
PARAMETER_VERSION: Final = "decision_params.v0"
TEMPLATE_VERSION: Final = "decision_templates.v0"


# --------------------------------------------------------------------------- closed enums
class Stance(StrEnum):
    STRONGLY_BULLISH = "Strongly Bullish"
    BULLISH = "Bullish"
    CAUTIOUSLY_BULLISH = "Cautiously Bullish"
    NEUTRAL = "Neutral / Wait"
    CAUTIOUSLY_BEARISH = "Cautiously Bearish"
    BEARISH = "Bearish"
    STRONGLY_BEARISH = "Strongly Bearish"
    INSUFFICIENT = "Insufficient Evidence"


class Confidence(StrEnum):
    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"
    INSUFFICIENT = "Insufficient Evidence"


class Posture(StrEnum):
    INVESTIGATE_FURTHER = "INVESTIGATE FURTHER"
    WAIT_FOR_CONFIRMATION = "WAIT FOR CONFIRMATION"
    MONITOR_CONSTRUCTIVE = "MONITOR CONSTRUCTIVE CONDITIONS"
    MONITOR_ELEVATED_CAUTION = "MONITOR WITH ELEVATED CAUTION"
    AVOID_ADDING_HIGH_RISK = "AVOID ADDING HIGH-RISK EXPOSURE"
    REASSESS_REDUCE_RISK = "REASSESS / REDUCE RISK"


class RiskLevel(StrEnum):
    LOW = "Low"
    MODERATE = "Moderate"
    ELEVATED = "Elevated"
    HIGH = "High"
    NOT_ASSESSED = "Not assessed"


class Direction(StrEnum):
    SUPPORTIVE = "S"
    ADVERSE = "A"
    NEUTRAL = "N"
    UNAVAILABLE = "U"


class Strength(StrEnum):
    STRONG = "Strong"
    MODERATE = "Moderate"
    WEAK = "Weak"
    MISSING = "Missing"


class Role(StrEnum):
    DIRECTIONAL = "Directional"
    RISK = "Risk"
    CONTEXT = "Context"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    NO_DATA = "no_data"
    NOT_ASSESSED = "not_assessed"  # the snapshot carries no freshness field (derivatives in v0)


class RiskDimension(StrEnum):
    MARKET = "market"
    LIQUIDITY = "liquidity"
    LEVERAGE = "leverage"
    VOLATILITY = "volatility"
    NARRATIVE = "narrative"
    DATA_QUALITY = "data_quality"


# Directional stance strength (INV-2 / INV-11 ordering (a)); Insufficient Evidence is outside it.
STANCE_STRENGTH: Final = MappingProxyType(
    {
        Stance.STRONGLY_BULLISH: 3,
        Stance.BULLISH: 2,
        Stance.CAUTIOUSLY_BULLISH: 1,
        Stance.NEUTRAL: 0,
        Stance.CAUTIOUSLY_BEARISH: 1,
        Stance.BEARISH: 2,
        Stance.STRONGLY_BEARISH: 3,
    }
)
BULLISH_FAMILY: Final = frozenset(
    {Stance.STRONGLY_BULLISH, Stance.BULLISH, Stance.CAUTIOUSLY_BULLISH}
)
BEARISH_FAMILY: Final = frozenset(
    {Stance.STRONGLY_BEARISH, Stance.BEARISH, Stance.CAUTIOUSLY_BEARISH}
)
# The bullish-family stance holding a given strength (used to express a ceiling).
BULLISH_BY_STRENGTH: Final = MappingProxyType(
    {
        0: Stance.NEUTRAL,
        1: Stance.CAUTIOUSLY_BULLISH,
        2: Stance.BULLISH,
        3: Stance.STRONGLY_BULLISH,
    }
)

# Posture permissiveness (ordering (b), decision D-O): higher = more permissive. INVESTIGATE
# FURTHER is outside the ordering (a coverage / data-quality state) and is absent on purpose.
POSTURE_PERMISSIVENESS: Final = MappingProxyType(
    {
        Posture.MONITOR_CONSTRUCTIVE: 5,
        Posture.MONITOR_ELEVATED_CAUTION: 4,
        Posture.AVOID_ADDING_HIGH_RISK: 3,
        Posture.WAIT_FOR_CONFIRMATION: 2,
        Posture.REASSESS_REDUCE_RISK: 1,
    }
)

CONFIDENCE_ORDER: Final = MappingProxyType(
    {Confidence.INSUFFICIENT: 0, Confidence.LOW: 1, Confidence.MODERATE: 2, Confidence.HIGH: 3}
)
RISK_ORDER: Final = MappingProxyType(
    {RiskLevel.LOW: 0, RiskLevel.MODERATE: 1, RiskLevel.ELEVATED: 2, RiskLevel.HIGH: 3}
)
RISK_BY_ORDER: Final = MappingProxyType({v: k for k, v in RISK_ORDER.items()})

# --------------------------------------------------------------------------- tools and scopes
TOOL_INSTITUTIONAL: Final = "get_institutional_flows"
TOOL_WHALE: Final = "get_whale_activity"
TOOL_LIQUIDITY: Final = "get_liquidity"
TOOL_MACRO: Final = "get_macro"
TOOL_MARKET_STRUCTURE: Final = "get_market_structure"
TOOL_DERIVATIVES: Final = "get_derivatives"
TOOL_RETAIL: Final = "get_retail_activity"
TOOL_ANOMALY: Final = "get_anomalies"
TOOL_REGIME: Final = "get_market_regime"
TOOL_SIMILARITY: Final = "find_historical_similar_periods"
TOOL_DIVERGENCE: Final = "calculate_divergence"
TOOL_ROTATION: Final = "get_capital_rotation"
TOOL_MARKET_DATA: Final = "get_market_data"

DOMAIN_TOOL: Final = MappingProxyType(
    {
        "institutional": TOOL_INSTITUTIONAL,
        "whale": TOOL_WHALE,
        "liquidity": TOOL_LIQUIDITY,
        "macro": TOOL_MACRO,
        "market_structure": TOOL_MARKET_STRUCTURE,
    }
)

# Expected directional domains per scope (decision D-J: D comes from the scope definition).
# SOL/XRP: whale activity is not tracked, so it is removed from D, never counted as negative.
# Only BTC is in the first release (D-K); the other definitions exist so D is data, not code.
SCOPE_DOMAINS: Final = MappingProxyType(
    {
        "BTC": ("institutional", "whale", "liquidity", "macro", "market_structure"),
        "ETH": ("institutional", "whale", "liquidity", "macro", "market_structure"),
        "SOL": ("institutional", "liquidity", "macro", "market_structure"),
        "XRP": ("institutional", "liquidity", "macro", "market_structure"),
    }
)
# Domains whose reading is asset-specific (looked up by ``asset == scope``).
ASSET_SPECIFIC_DOMAINS: Final = frozenset({"institutional", "whale"})
# "Key confirmation layer" per scope (CN-06 / PO-04): BTC/ETH institutional or whale; SOL/XRP
# institutional.
KEY_CONFIRMATION_DOMAINS: Final = MappingProxyType(
    {
        "BTC": ("institutional", "whale"),
        "ETH": ("institutional", "whale"),
        "SOL": ("institutional",),
        "XRP": ("institutional",),
    }
)

# --------------------------------------------------------------------------- band vocabulary
# Exact band strings (matched exactly; unrecognised -> reading U with RD-09). Source: each domain's
# own ``score_parameters`` / ``score`` module. (direction, is_strong_band)
_BandMap = MappingProxyType  # alias for readability

DOMAIN_BANDS: Final = MappingProxyType(
    {
        "institutional": MappingProxyType(
            {
                "strong net inflow": (Direction.SUPPORTIVE, True),
                "net inflow": (Direction.SUPPORTIVE, False),
                "balanced": (Direction.NEUTRAL, False),
                "net outflow": (Direction.ADVERSE, False),
                "strong net outflow": (Direction.ADVERSE, True),
            }
        ),
        "whale": MappingProxyType(
            {
                "strong accumulation": (Direction.SUPPORTIVE, True),
                "accumulation": (Direction.SUPPORTIVE, False),
                "neutral": (Direction.NEUTRAL, False),
                "distribution": (Direction.ADVERSE, False),
                "strong distribution": (Direction.ADVERSE, True),
            }
        ),
        "liquidity": MappingProxyType(
            {
                "strong liquidity expansion": (Direction.SUPPORTIVE, True),
                "liquidity expansion": (Direction.SUPPORTIVE, False),
                "stable": (Direction.NEUTRAL, False),
                "liquidity contraction": (Direction.ADVERSE, False),
                "strong liquidity contraction": (Direction.ADVERSE, True),
            }
        ),
        "macro": MappingProxyType(
            {
                "broadly accommodative macro backdrop": (Direction.SUPPORTIVE, True),
                "improving macro backdrop": (Direction.SUPPORTIVE, False),
                "neutral / mixed macro backdrop": (Direction.NEUTRAL, False),
                "tightening macro backdrop": (Direction.ADVERSE, False),
                "broadly restrictive macro backdrop": (Direction.ADVERSE, True),
            }
        ),
        "market_structure": MappingProxyType(
            {
                "broadly constructive technical structure": (Direction.SUPPORTIVE, True),
                "improving technical structure": (Direction.SUPPORTIVE, False),
                "neutral / mixed technical structure": (Direction.NEUTRAL, False),
                "deteriorating technical structure": (Direction.ADVERSE, False),
                "broadly weak technical structure": (Direction.ADVERSE, True),
            }
        ),
    }
)

REGIME_IDS: Final = frozenset(
    {
        "accumulation",
        "recovery",
        "expansion",
        "euphoria",
        "distribution",
        "capitulation",
        "mixed_unclear",
    }
)
DERIVATIVES_BANDS: Final = frozenset(
    {"low stress", "moderate stress", "elevated stress", "high stress"}
)
ANOMALY_BANDS: Final = frozenset(
    {"extreme_high", "notable_high", "normal", "notable_low", "extreme_low"}
)
EXTREME_ANOMALY_BANDS: Final = frozenset({"extreme_high", "extreme_low"})

# Risk-level maps (RK-01..RK-05). Judgment parameters (J-risk).
REGIME_MARKET_RISK: Final = MappingProxyType(
    {
        "accumulation": RiskLevel.LOW,
        "recovery": RiskLevel.LOW,
        "expansion": RiskLevel.LOW,
        "mixed_unclear": RiskLevel.MODERATE,
        "euphoria": RiskLevel.ELEVATED,
        "distribution": RiskLevel.ELEVATED,
        "capitulation": RiskLevel.HIGH,
    }
)
DERIVATIVES_RISK: Final = MappingProxyType(
    {
        "low stress": RiskLevel.LOW,
        "moderate stress": RiskLevel.MODERATE,
        "elevated stress": RiskLevel.ELEVATED,
        "high stress": RiskLevel.HIGH,
    }
)
VOLATILITY_RISK: Final = MappingProxyType(
    {
        "normal": RiskLevel.LOW,
        "notable_low": RiskLevel.MODERATE,
        "extreme_low": RiskLevel.MODERATE,
        "notable_high": RiskLevel.ELEVATED,
        "extreme_high": RiskLevel.HIGH,
    }
)
RETAIL_ACTIVITY_RISK: Final = MappingProxyType(
    {
        "quiet retail-proxy activity": RiskLevel.LOW,
        "below-normal retail-proxy activity": RiskLevel.LOW,
        "typical retail-proxy activity": RiskLevel.LOW,
        "above-normal retail-proxy activity": RiskLevel.MODERATE,
        "elevated retail-proxy activity": RiskLevel.ELEVATED,
    }
)
RETAIL_SPECULATION_RISK: Final = MappingProxyType(
    {
        "balanced": RiskLevel.LOW,
        "short-biased speculative skew": RiskLevel.LOW,
        "long-biased speculative skew": RiskLevel.MODERATE,
        "strong short-biased speculative skew": RiskLevel.MODERATE,
        "strong long-biased speculative skew": RiskLevel.ELEVATED,
    }
)
_ELEVATED_ACTIVITY: Final = "elevated retail-proxy activity"
_STRONG_LONG_SKEW: Final = "strong long-biased speculative skew"


# --------------------------------------------------------------------------- parameters
@dataclass(frozen=True, slots=True)
class DecisionParameters:
    """The v0 judgment parameters. Fractions are ``(numerator, denominator)`` integer pairs so every
    comparison is exact integer arithmetic (no floating point, methodology X6)."""

    version: str = PARAMETER_VERSION
    methodology_version: str = METHODOLOGY_VERSION
    template_version: str = TEMPLATE_VERSION
    coverage_floor: tuple[int, int] = (1, 2)  # c < 1/2  -> Insufficient Evidence (DS-01)
    strongly_coverage: tuple[int, int] = (3, 4)  # c >= 3/4 for a "Strongly" stance (DS-03/09)
    ratio_plain: tuple[int, int] = (3, 5)  # r >= 3/5 -> Bullish / Bearish tier (DS-04/08)
    ratio_cautious: tuple[int, int] = (3, 10)  # r >= 3/10 -> Cautiously tier (DS-05/07)
    conflict_min_each_side: int = 2  # DS-02: S >= 2 and A >= 2
    confidence_high: tuple[int, int] = (85, 100)  # CN-01
    confidence_moderate: tuple[int, int] = (65, 100)  # CN-01
    constructive_max_not_assessed: int = 2  # PO-05: n_NA <= 2
    data_quality_by_unavailable: tuple[RiskLevel, ...] = (
        RiskLevel.LOW,
        RiskLevel.MODERATE,
        RiskLevel.ELEVATED,
        RiskLevel.HIGH,
    )  # RK-06: u = 0, 1, 2, >= 3
    # Domain score versions the engine assumes (D-G). Institutional and whale scores carry no
    # version in the snapshot; the engine records these assumed ids with every assessment.
    assumed_domain_score_versions: tuple[tuple[str, str], ...] = (
        ("institutional", "v1"),
        ("whale", "v1"),
        ("liquidity", "liquidity_score_v1"),
        ("macro", "macro_score_v1"),
        ("market_structure", "market_structure_score_v1"),
        ("derivatives", "derivatives_health_v1"),
        ("retail_activity", "retail_activity_score_v1"),
        ("retail_speculation", "retail_speculation_score_v1"),
    )


PARAMETERS_V0: Final = DecisionParameters()
RETAIL_ELEVATED_ACTIVITY_BAND: Final = _ELEVATED_ACTIVITY
RETAIL_STRONG_LONG_BAND: Final = _STRONG_LONG_SKEW

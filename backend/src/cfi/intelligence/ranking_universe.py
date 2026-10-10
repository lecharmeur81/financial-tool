"""Versioned vocabulary of the Opportunity Scoring & Ranking engine (Phase 47; ADR-0084).

Closed ids and the experimental parameters live here as data. ``evidence_depth`` is an ordinal
index of how much eligible, verified *asset-specific* supporting evidence a Phase 46 candidate has.
It is a design heuristic, not a validated predictor: it is not a probability, a confidence, an
expected return or a recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "COMPONENTS",
    "COMPONENTS_VERSION",
    "LIMITATIONS",
    "NOTES",
    "NOTICE",
    "RANKING_PARAMS_V0",
    "REASONS",
    "SCORED_STRENGTHS",
    "SUPPORTED_DISCOVERY_TYPES_VERSION",
    "SUPPORTED_OPPORTUNITY_PARAMS_VERSION",
    "WITHHELD_REASONS",
    "RankingParameters",
]

PARAMETER_VERSION: Final = "ranking_params.v0"
COMPONENTS_VERSION: Final = "ranking_components.v0"
# The Phase 46 vocabulary this engine was written against; any other version is refused.
SUPPORTED_OPPORTUNITY_PARAMS_VERSION: Final = "opportunity_params.v0"
SUPPORTED_DISCOVERY_TYPES_VERSION: Final = "discovery_types.v0"

# Only these strengths can belong to an eligible supporting member (a flag makes it Weak, and a
# flagged member is not eligible). Anything else on an eligible supporting member is inconsistent.
SCORED_STRENGTHS: Final = ("Strong", "Moderate")

COMPONENTS: Final = (
    ("family_base", "One point for each distinct eligible asset-specific supporting family."),
    (
        "strong_bonus",
        "One further point for each such family with at least one eligible Strong member, "
        "however many Strong members it has.",
    ),
    (
        "market_wide_context",
        "Market-wide supporting families are shown for context and contribute zero points.",
    ),
)

REASONS: Final = (
    ("RK-SCORED", "A Phase 46 candidate was given an evidence depth."),
    ("RK-RANKED", "Ranked against the other scored assets of its comparability group."),
    (
        "RK-NOT-RANKED-SOLE-IN-GROUP",
        "It is the only scored asset in its comparability group, so there is nothing to rank "
        "it against.",
    ),
    (
        "RK-NOT-RANKED-COMPARABILITY-UNVERIFIED",
        "Its comparability relationships are inconsistent or not reciprocal, so it is not "
        "ranked against any other asset.",
    ),
    ("RK-WITHHELD-NOT-CANDIDATE", "Phase 46 did not report a candidate; nothing is scored."),
    (
        "RK-WITHHELD-BLOCKED",
        "Phase 46 withheld this candidate under an integrity gate; nothing is scored.",
    ),
    ("RK-GATE-LOOK-AHEAD", "The snapshot reports look-ahead violations; no asset is scored."),
    ("RK-GATE-INTEGRITY", "The snapshot producer hash does not verify; no asset is scored."),
)
NOTES: Final = (
    (
        "RK-UNEQUAL-ELIGIBLE-COVERAGE",
        "Assets of this group have different eligible coverage; a lower depth can reflect "
        "missing evidence rather than weaker evidence.",
    ),
    (
        "RK-SHARED-MARKET-WIDE-EVIDENCE",
        "Market-wide evidence is shared with other candidates; it is not counted in the depth.",
    ),
    (
        "RK-NOT-COMPARABLE-ACROSS-GROUPS",
        "Assets with different expected evidence are never ranked against each other.",
    ),
)
# Why a score is withheld (never a number): mirrors the Phase 46 status it comes from; gate
# reason codes are reported separately and never replace it.
WITHHELD_REASONS: Final = (
    "blocked_by_integrity_gate",
    "conflicting_evidence",
    "insufficient_evidence",
    "no_candidate",
)


@dataclass(frozen=True, slots=True)
class RankingParameters:
    version: str = PARAMETER_VERSION
    family_base_points: int = 1
    strong_bonus_points: int = 1
    market_wide_points: int = 0
    min_scored_to_rank: int = 2  # scored assets needed in one group before any rank is given


RANKING_PARAMS_V0: Final = RankingParameters()

NOTICE: Final = (
    "evidence_depth_not_a_forecast",
    "Evidence depth counts the verified asset-specific evidence families that support a "
    "candidate, under an experimental heuristic. It is not a probability, a confidence, an "
    "expected return or a recommendation, and it has not been validated against outcomes.",
)

LIMITATIONS: Final = (
    (
        "heuristic_not_validated",
        "The index and its equal one-point rules are design choices; they have not been "
        "validated against historical outcomes (Phase 50).",
    ),
    (
        "coarse_scale",
        "The index takes at most five values (0 to 4 possible, 1 to 4 once scored), so many "
        "assets tie.",
    ),
    (
        "strength_is_band_derived",
        "Strong means an extreme domain band, not a measured size; underlying domain score "
        "magnitudes are not used.",
    ),
    (
        "asset_specific_evidence_only",
        "Only institutional and whale evidence counts. BTC and ETH can reach 4; SOL and XRP "
        "have no whale data and can reach at most 2.",
    ),
    (
        "market_wide_evidence_not_counted",
        "Liquidity, macro and market structure are shared by every asset and may be correlated, "
        "so they add nothing to the index.",
    ),
    (
        "structural_comparability",
        "Groups are formed from the evidence each asset is expected to have, not from how much "
        "it has today.",
    ),
    (
        "no_risk_or_decision",
        "There is no risk, invalidation, decision, backtest or alert here (Phases 48 to 52).",
    ),
)

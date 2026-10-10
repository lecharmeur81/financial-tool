"""Versioned vocabulary of the Opportunity Discovery Engine (Phase 46; ADR-0083).

Closed ids and the experimental parameters live here as data. Nothing in this module is a
validated predictor: a *candidate* is an asset whose current, verified evidence is worth further
research, not a forecast, a recommendation or an instruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "AGREEMENTS",
    "DISCOVERY_TYPES",
    "DISCOVERY_TYPES_VERSION",
    "LIMITATIONS",
    "NOTICE",
    "OPPORTUNITY_PARAMS_V0",
    "REASONS",
    "STATUSES",
    "SUPPORTED_CONFIRMATION_FAMILIES_VERSION",
    "SUPPORTED_CONFIRMATION_PARAMS_VERSION",
    "OpportunityParameters",
]

DISCOVERY_TYPES_VERSION: Final = "discovery_types.v0"
PARAMETER_VERSION: Final = "opportunity_params.v0"
# The Phase 45 vocabulary this engine was written against; any other version is refused.
SUPPORTED_CONFIRMATION_PARAMS_VERSION: Final = "confirmation_params.v0"
SUPPORTED_CONFIRMATION_FAMILIES_VERSION: Final = "evidence_families.v0"

STATUSES: Final = (
    "candidate",
    "conflicting_evidence",
    "insufficient_evidence",
    "no_candidate",
    "blocked",
)
AGREEMENTS: Final = (
    "confirmed_supportive",
    "confirmed_adverse",
    "mixed",
    "unconfirmed",
    "insufficient_evidence",
)
DISCOVERY_TYPES: Final = (
    ("asset_led_confirmation", "two or more asset-specific families confirm"),
    ("market_aligned_confirmation", "one asset-specific family and market-wide families confirm"),
    (
        "adverse_confirmation",
        "adverse confirmation, kept as a review outcome and never a candidate",
    ),
)

REASONS: Final = (
    ("OD-CANDIDATE", "Phase 45 confirmed supportive evidence with an asset-specific confirmer."),
    ("OD-CONFLICT", "Eligible evidence exists on both sides."),
    ("OD-INSUFFICIENT", "Eligible coverage is below the confirmation floor."),
    ("OD-UNCONFIRMED", "Eligible evidence is not confirmed by enough independent families."),
    ("OD-ADVERSE-CONFIRMATION", "Adverse evidence is confirmed; this is a review outcome only."),
    ("OD-NO-ASSET-SPECIFIC-CONFIRMER", "No eligible asset-specific confirmer supports it."),
    ("OD-UNVERIFIED-SUPPORT", "A supporting member lacks eligibility or verified freshness."),
    ("OD-LOOK-AHEAD-VIOLATION", "The snapshot reports look-ahead violations; candidates blocked."),
    ("OD-SNAPSHOT-INTEGRITY", "The snapshot producer hash does not verify; candidates blocked."),
)
NOTES: Final = (
    ("OD-NOT-COMPARABLE-COVERAGE", "Assets are assessed over different sets of expected domains."),
    ("OD-SHARED-MARKET-WIDE-EVIDENCE", "Market-wide evidence is shared with other candidates."),
)


@dataclass(frozen=True, slots=True)
class OpportunityParameters:
    version: str = PARAMETER_VERSION
    min_asset_specific_confirmers: int = 1  # distinct asset-specific supporting families
    asset_led_min_asset_specific: int = 2  # asset-specific families for ``asset_led_confirmation``


OPPORTUNITY_PARAMS_V0: Final = OpportunityParameters()

NOTICE: Final = (
    "research_candidates_only",
    "A candidate is an asset whose current, verified evidence merits further research. It is not a "
    "prediction, a recommendation or an instruction.",
)

LIMITATIONS: Final = (
    (
        "confirmation_is_agreement_not_performance",
        "Confirmation means independent data families agree today; it says nothing about future "
        "performance.",
    ),
    (
        "experimental_parameters",
        "Thresholds are experimental engineering heuristics, not validated predictors.",
    ),
    (
        "four_asset_universe",
        "Only BTC, ETH, SOL and XRP are assessed; whale data covers BTC and ETH only.",
    ),
    (
        "market_wide_evidence_shared",
        "Liquidity, macro and market structure are the same for every asset, so assets confirmed "
        "through them are not independent of each other.",
    ),
    (
        "inputs_limited_to_unified_and_confirmation",
        "Relative strength, capital rotation and institutional-versus-retail divergence are not "
        "used in this version.",
    ),
    (
        "no_ranking_or_decision",
        "Assets are listed in a fixed order; there is no scoring, ranking, risk assessment or "
        "investment decision here.",
    ),
)

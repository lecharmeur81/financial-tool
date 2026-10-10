"""Versioned vocabulary of the Investment Decision engine (Phase 49; ADR-0086).

A decision state is a research classification of one opportunity under the evidence and risk
findings of Phases 45 to 48. It is not an investment recommendation, not a stance or posture of the
Decision Intelligence layer (``cfi.decision``), not a confirmed thesis and never a safety rating.
Nothing here is a validated predictor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "DETECTED_LIMITATION_CHECKS",
    "INVESTMENT_PARAMS_V0",
    "LIMITATIONS",
    "NOTICE",
    "PARAMETER_VERSION",
    "PRECEDENCE",
    "REASONS",
    "STATES",
    "STATES_VERSION",
    "InvestmentParameters",
]

PARAMETER_VERSION: Final = "investment_params.v0"
STATES_VERSION: Final = "investment_states.v0"

# state id, meaning. Ordered from the most restrictive to the least: this is also the precedence.
STATES: Final = (
    (
        "withheld_integrity_gate",
        "A look-ahead or producer-hash integrity gate is triggered; nothing is assessed.",
    ),
    (
        "candidate_invalidation_triggered",
        "A Phase 46 candidate whose Phase 48 invalidation summary is triggered.",
    ),
    (
        "contradicted_evidence",
        "Eligible evidence exists on both sides, or adverse evidence is confirmed (Phase 46).",
    ),
    (
        "insufficient_evidence",
        "Eligible coverage is below the confirmation floor (Phase 46). Not adverse evidence.",
    ),
    ("no_opportunity", "Phase 46 reports no candidate and no conflict or gap."),
    (
        "candidate_risk_findings_detected",
        "A candidate with at least one detected Phase 48 risk or integrity finding. A risk "
        "finding is not an invalidation.",
    ),
    (
        "candidate_unresolved",
        "A candidate with no detected risk finding but unresolved checks: unverified, unavailable, "
        "not applicable, an evidence limitation, or an invalidation that cannot be evaluated.",
    ),
    (
        "candidate_no_findings_detected",
        "A candidate with no detected finding, every evaluated check passed on verified-fresh "
        "evidence and no invalidation triggered. Not a confirmed thesis and not safe: the "
        "declared-unavailable checks are still not evaluated.",
    ),
)
# The order in which a state is chosen. The first applicable rule wins; the rest is still reported.
PRECEDENCE: Final = tuple(s for s, _ in STATES)

# Phase 48 checks that describe evidence coverage or dependence, not risk. When detected they make
# a candidate unresolved; they are never risk findings and never adverse evidence.
DETECTED_LIMITATION_CHECKS: Final = {
    "RI-EVD-03": "DI-EVIDENCE-INCOMPLETE",
    "RI-EVD-04": "DI-EVIDENCE-THIN",
    "RI-EVD-05": "DI-SHARED-EVIDENCE",
}

REASONS: Final = (
    ("DI-GATE-WITHHELD", "An integrity gate is triggered; the asset is withheld."),
    ("DI-GATE-LOOK-AHEAD", "The snapshot reports look-ahead violations."),
    ("DI-GATE-INTEGRITY", "The producer hash does not verify."),
    ("DI-INVALIDATION-TRIGGERED", "Phase 48 reports a triggered invalidation condition."),
    ("DI-CONTRADICTED", "Phase 46 reports conflicting or adverse-confirmed evidence."),
    ("DI-INSUFFICIENT-EVIDENCE", "Phase 46 reports insufficient eligible evidence."),
    ("DI-NO-OPPORTUNITY", "Phase 46 reports no candidate."),
    ("DI-RISK-FINDINGS-DETECTED", "At least one Phase 48 risk or integrity finding is detected."),
    ("DI-SOURCE-CONFLICT", "Tools report conflicting or degraded data."),
    ("DI-UNRESOLVED", "Checks remain unresolved; see the listed reasons."),
    ("DI-UNVERIFIED-CHECKS", "Some checks are evaluable but their freshness is unverified."),
    ("DI-UNAVAILABLE-CHECKS", "Some checks have missing data or an unevaluable source."),
    ("DI-NOT-APPLICABLE-CHECKS", "Some checks do not apply (for example caps not evaluated)."),
    ("DI-INVALIDATION-NOT-FULLY-EVALUABLE", "Some invalidation conditions cannot be evaluated."),
    ("DI-EVIDENCE-INCOMPLETE", "Expected evidence domains are unusable (missing, not adverse)."),
    ("DI-EVIDENCE-THIN", "Fewer than two asset-specific families support the candidate."),
    (
        "DI-SHARED-EVIDENCE",
        "The candidate relies on market-wide evidence shared with other assets.",
    ),
    ("DI-NO-FINDINGS-DETECTED", "No finding is detected among the evaluated checks."),
    (
        "DI-CANDIDATE-IS-NOT-A-THESIS",
        "A candidate is an eligible opportunity, not a confirmed thesis.",
    ),
    ("DI-DECLARED-CHECKS-NOT-EVALUATED", "Declared-unavailable checks are not evaluated."),
    (
        "DI-NO-RISK-ASSESSMENT",
        "Phase 48 performed no risk assessment for this asset (withheld or not a candidate). "
        "Empty findings and zero counts are not a clean result.",
    ),
    ("DI-UNDERLYING-STATUS", "The Phase 46 status is preserved beside a gate-withheld state."),
)

NOTICE: Final = (
    "research_state_not_a_recommendation",
    "A decision state classifies how far the existing evidence and risk findings go. It is not a "
    "recommendation, an instruction, a probability, a target, a confirmed thesis or a safety "
    "rating, and it is separate from the Decision Intelligence stance and posture.",
)

LIMITATIONS: Final = (
    (
        "state_is_not_a_thesis",
        "The strongest state, candidate_no_findings_detected, means no finding was detected among "
        "the evaluated checks. It does not mean the thesis is confirmed or the candidate is safe.",
    ),
    (
        "strongest_states_not_reachable_on_live_data",
        "On current live data candidate_no_findings_detected is not reachable: the data-quality "
        "check (RI-DQ-01) is always unverified and risk-role freshness cannot be verified. "
        "candidate_invalidation_triggered is not reachable for any input Phase 48 accepts.",
    ),
    (
        "overlapping_inputs",
        "Opportunities, ranking and risk are views of one stored snapshot. They are not "
        "independent confirmations and no finding is strengthened by appearing in more than one.",
    ),
    (
        "ranking_is_context_only",
        "The Phase 47 evidence depth and rank are shown and never used to choose a state.",
    ),
    (
        "reassessment_is_observational",
        "Reassessment items restate Phase 48 monitor fields and unresolved checks. They contain no "
        "price target, numeric threshold or timing rule.",
    ),
    ("no_alert_or_backtest", "There is no backtest or alert here (Phases 50 to 52)."),
)


@dataclass(frozen=True, slots=True)
class InvestmentParameters:
    version: str = PARAMETER_VERSION
    states_version: str = STATES_VERSION


INVESTMENT_PARAMS_V0: Final = InvestmentParameters()

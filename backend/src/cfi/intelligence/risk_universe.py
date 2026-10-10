"""Versioned vocabulary of the Risk & Invalidation engine (Phase 48; ADR-0085).

Everything the engine reports is named here as data. Nothing in this module is a validated
predictor: risk levels are the decision engine's own v0 design judgments (``cfi.decision``), not
probabilities of loss, and ``passed`` never means *safe*."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "CAP_RULES",
    "CHECKS",
    "CHECKS_VERSION",
    "DECLARED_UNAVAILABLE",
    "INVALIDATION_CONDITIONS",
    "INVALIDATION_RESULTS",
    "LIMITATIONS",
    "NOTICE",
    "REASONS",
    "RESULTS",
    "RISK_PARAMS_V0",
    "RiskParameters",
]

PARAMETER_VERSION: Final = "risk_params.v0"
CHECKS_VERSION: Final = "risk_checks.v0"

# Result of one risk check. ``passed`` is deliberately narrow: the condition is not met AND the
# evidence behind it is verified fresh. It never means safe.
RESULTS: Final = (
    (
        "passed",
        "The condition is not met, on verified-fresh evidence. This is not a safety rating.",
    ),
    ("detected", "The condition is met. Reported even when freshness is unverified (flagged)."),
    ("unverified", "Evaluable, but freshness cannot be verified; this is not reassuring."),
    ("unavailable", "The required data is missing or the source could not be evaluated."),
    ("not_applicable", "The check does not apply here (the reason is stated)."),
    ("withheld", "An integrity gate is triggered; nothing is assessed."),
)
INVALIDATION_RESULTS: Final = (
    ("triggered", "The invalidation condition is met."),
    ("not_triggered", "The condition is not met, on verified-fresh evidence."),
    ("cannot_evaluate", "The condition cannot be established from the available evidence."),
    ("withheld", "An integrity gate is triggered; nothing is assessed."),
)

# check_id, category, scope ("integrity" / "market" / "asset"), what is checked
CHECKS: Final = (
    ("RI-INT-01", "integrity", "integrity", "The snapshot reports no look-ahead violation."),
    ("RI-INT-02", "integrity", "integrity", "The producer payload hash verifies."),
    ("RI-INT-03", "integrity", "integrity", "Tools report no conflicting or degraded data."),
    ("RI-MKT-01", "market_stress", "market", "Decision engine RK-01 market risk below Elevated."),
    ("RI-LIQ-01", "liquidity_backdrop", "market", "Decision engine RK-02 below Elevated."),
    ("RI-VOL-01", "volatility", "market", "Decision engine RK-04 volatility below Elevated."),
    ("RI-NAR-01", "speculation", "market", "Decision engine RK-05 retail risk below Elevated."),
    ("RI-LEV-01", "leverage", "asset", "Decision engine RK-03 derivatives risk below Elevated."),
    (
        "RI-DQ-01",
        "data_quality",
        "asset",
        "Decision engine RK-06 data-quality risk below Elevated.",
    ),
    (
        "RI-EVD-01",
        "evidence_disagreement",
        "asset",
        "Among the eligible asset-specific members, none is adverse. Members excluded as missing, "
        "stale or unverified are not examined here (see RI-EVD-03).",
    ),
    (
        "RI-EVD-02",
        "evidence_disagreement",
        "asset",
        "Among the eligible market-wide members, none is adverse. Members excluded as missing, "
        "stale or unverified are not examined here (see RI-EVD-03).",
    ),
    ("RI-EVD-03", "coverage", "asset", "Every expected evidence domain is eligible and verified."),
    (
        "RI-EVD-04",
        "coverage",
        "asset",
        "At least two distinct asset-specific families are among the eligible supporting members "
        "(a count; it says nothing about the quality or freshness of the evidence).",
    ),
    (
        "RI-EVD-05",
        "evidence_dependence",
        "asset",
        "No market-wide family is among the eligible supporting members (a count).",
    ),
    ("RI-CAP-01", "decision_caps", "asset", "Observed cap RC-01: derivatives high stress."),
    ("RI-CAP-02", "decision_caps", "asset", "Observed cap RC-02: critical anomaly."),
    ("RI-CAP-03", "decision_caps", "asset", "Observed cap RC-03: euphoria regime."),
    ("RI-CAP-04", "decision_caps", "asset", "Observed cap RC-04: distribution or capitulation."),
)
# The decision-engine cap rules and what each depends on (cfi.decision.rules.apply_limits).
# rule id, check id, the domain whose reading it depends on, what it says
CAP_RULES: Final = (
    ("RC-01", "RI-CAP-01", "derivatives", "derivatives band is 'high stress'"),
    ("RC-02", "RI-CAP-02", "anomaly", "a critical (extreme) anomaly is present"),
    ("RC-03", "RI-CAP-03", "regime", "regime is 'euphoria'"),
    ("RC-04", "RI-CAP-04", "regime", "regime is 'distribution' or 'capitulation'"),
)
# Not evaluated: no verified source exists in the contracts, so each is reported unavailable.
DECLARED_UNAVAILABLE: Final = (
    (
        "RI-UNV-EXECUTION",
        "execution_liquidity",
        "RI-NO-VERIFIED-DATA",
        "Order-book depth, spread and slippage are not in the snapshot. The 'liquidity' risk "
        "here is the stablecoin-supply backdrop, not execution depth.",
    ),
    (
        "RI-UNV-DERIVATIVES-DETAIL",
        "leverage",
        "RI-NO-VERIFIED-DATA",
        "Funding, open-interest and liquidation magnitudes are not in the contracts; only the "
        "derivatives stress band is.",
    ),
    (
        "RI-UNV-EVIDENCE-TREND",
        "evidence_deterioration",
        "RI-NO-VERIFIED-DATA",
        "A snapshot is one point in time; institutional or on-chain deterioration cannot be "
        "measured without history.",
    ),
    (
        "RI-UNV-EVENT-RISK",
        "event_risk",
        "RI-NO-VERIFIED-DATA",
        "No scheduled-event or calendar source exists.",
    ),
    (
        "RI-UNV-VENUE",
        "counterparty",
        "RI-NO-VERIFIED-DATA",
        "Venue, custody and counterparty risk are not measured.",
    ),
    (
        "RI-UNV-PORTFOLIO",
        "position_concentration",
        "RI-NOT-KNOWN-TO-PLATFORM",
        "The platform does not know the user's holdings, goals or risk tolerance.",
    ),
)
# id, what must hold for the candidate to stay valid. Restated from existing rules; no new numbers.
INVALIDATION_CONDITIONS: Final = (
    (
        "INV-01",
        "asset_specific_support_lost",
        "No distinct asset-specific family supports the candidate (Phase 46 minimum).",
    ),
    (
        "INV-02",
        "confirmation_lost",
        "Fewer than the Phase 45 minimum of distinct supportive families confirm.",
    ),
    ("INV-03", "adverse_confirmation", "Adverse eligible evidence appears (Phase 45 'mixed')."),
    (
        "INV-04",
        "freshness_verification_status",
        "Every supporting member has verified-fresh evidence. A snapshot is one point in time and "
        "no contract records an earlier verified state, so a loss of freshness cannot be observed: "
        "this condition is never triggered, only not_triggered or cannot_evaluate.",
    ),
    ("INV-05", "integrity_gate", "A look-ahead or producer-hash integrity gate is triggered."),
    (
        "INV-06",
        "decision_cap",
        "A decision-engine cap (RC-01 to RC-04) is observed. The decision rules limit a decision "
        "stance; they do not establish that an opportunity candidate is invalid.",
    ),
)

REASONS: Final = (
    ("RI-ASSESSED", "A Phase 46 candidate was assessed."),
    ("RI-NOT-A-CANDIDATE", "Phase 46 did not report a candidate; nothing is assessed."),
    ("RI-WITHHELD-BLOCKED", "Phase 46 withheld this candidate under an integrity gate."),
    ("RI-GATE-LOOK-AHEAD", "The snapshot reports look-ahead violations; nothing is assessed."),
    ("RI-GATE-INTEGRITY", "The producer hash does not verify; nothing is assessed."),
    ("RI-FRESHNESS-UNVERIFIED", "The evidence's freshness cannot be verified."),
    (
        "RI-FRESHNESS-LOSS-NOT-OBSERVABLE",
        "No contract records a change from verified to unverified freshness; stale or unverified "
        "evidence is not an observed loss and is not proof that a thesis failed.",
    ),
    ("RI-NO-ELIGIBLE-MEMBERS-IN-SCOPE", "No eligible member is in scope, so nothing was examined."),
    ("RI-FRESHNESS-NOT-APPLICABLE", "The level is derived from counts, not from a dated source."),
    ("RI-LEVEL-MODERATE-VISIBLE", "Moderate is shown but is below the detection threshold."),
    ("RI-LEVEL-NOT-ASSESSED", "The decision engine could not assess this dimension."),
    ("RI-MISSING-NOT-ADVERSE", "Missing or unusable evidence is reported; it is not adverse."),
    ("RI-CAP-NOT-EVALUATED-RAW-NOT-BULLISH", "Cap rules apply only to a bullish raw stance."),
    ("RI-CAP-SOURCE-NOT-EVALUABLE", "The cap's source could not be evaluated (CAP-U applies)."),
    ("RI-CAP-OBSERVED", "The cap is observed; binding is reported separately."),
    ("RI-INV-CAP-RELATIONSHIP-NOT-ESTABLISHED", "No rule ties a cap to candidate invalidity."),
    ("RI-NO-VERIFIED-DATA", "No verified source for this check exists in the contracts."),
    ("RI-NOT-KNOWN-TO-PLATFORM", "The platform does not hold this information."),
    ("RI-HASH-UNVERIFIED", "No stored producer hash was supplied to verify against."),
    ("RI-SOURCE-CONFLICT", "Tools report conflicting or degraded data."),
)

NOTICE: Final = (
    "risk_findings_not_a_safety_rating",
    "These are explicit findings from existing v0 risk rules. They are not a probability of loss, "
    "a safety rating, a recommendation or an instruction, and 'passed' does not mean safe.",
)

LIMITATIONS: Final = (
    (
        "risk_levels_are_design_judgments",
        "Risk levels and band mappings are the decision engine's v0 judgment parameters, not "
        "probabilities of loss and not validated predictors.",
    ),
    (
        "risk_role_freshness_unverified",
        "Derivatives, anomaly, retail and regime readings do not carry verifiable freshness in "
        "current snapshots, so their low readings are reported as unverified, never as passed.",
    ),
    (
        "overlapping_inputs",
        "Ranking, opportunity discovery and the risk view are derived from one stored snapshot. "
        "They are not independent confirmations and must not be counted as such.",
    ),
    (
        "caps_depend_on_raw_stance",
        "The decision engine evaluates caps only for a bullish raw stance; otherwise they are "
        "reported not applicable, not as absent.",
    ),
    (
        "cap_invalidation_not_established",
        "No existing rule makes a cap an invalidation of a candidate; caps are risk findings and "
        "the related invalidation condition is cannot_evaluate.",
    ),
    (
        "not_evaluated_checks",
        "Execution liquidity, numeric derivatives risk, evidence trends, event risk, venue risk "
        "and position concentration are declared unavailable.",
    ),
    (
        "freshness_loss_not_observable",
        "A snapshot is one point in time. No contract records an earlier verified state, so stale, "
        "missing or unverified freshness is never reported as a lost verification (INV-04).",
    ),
    (
        "evidence_checks_limited_in_scope",
        "RI-EVD-01 and RI-EVD-02 examine only the members Phases 45 and 46 admitted as eligible. A "
        "pass does not mean all relevant evidence was examined, that other evidence is fresh, or "
        "that a thesis is safe. RI-EVD-04 and RI-EVD-05 are counts of families.",
    ),
    (
        "no_decision",
        "There is no investment decision, backtest or alert here (Phases 49 to 52).",
    ),
)


@dataclass(frozen=True, slots=True)
class RiskParameters:
    version: str = PARAMETER_VERSION
    # A risk level is a detected condition only at these levels; Moderate is visible, not detected.
    detected_levels: tuple[str, ...] = ("Elevated", "High")
    visible_levels: tuple[str, ...] = ("Moderate",)


RISK_PARAMS_V0: Final = RiskParameters()

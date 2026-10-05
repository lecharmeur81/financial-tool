"""Typed, immutable assessment result (L4.5 output). Contains identifiers only — stance, confidence
and posture are closed enums, every text field is a template id, and no field holds a price,
target, probability or percentage (INV P11)."""

from __future__ import annotations

from dataclasses import dataclass

from cfi.decision.evidence import EvidenceReading
from cfi.decision.universe import (
    Confidence,
    Direction,
    Posture,
    RiskDimension,
    RiskLevel,
    Stance,
    Strength,
)

__all__ = [
    "AssessmentResult",
    "CapRecord",
    "CapUApplication",
    "EvidenceItem",
    "Explanation",
    "RiskReading",
    "Tally",
]


@dataclass(frozen=True, slots=True)
class Tally:
    """Directional tally. ``D = S + A + N + U`` (unavailable readings stay in D)."""

    s: int
    a: int
    n_neutral: int
    u: int
    s_strong: int
    a_strong: int

    @property
    def d(self) -> int:
        return self.s + self.a + self.n_neutral + self.u

    @property
    def n(self) -> int:
        """Available directional readings: ``n = S + A + N``."""
        return self.s + self.a + self.n_neutral

    @property
    def balance_numerator(self) -> int:
        """``S - A``; the balance is ``(S - A) / D`` and is never computed in floating point."""
        return self.s - self.a


@dataclass(frozen=True, slots=True)
class RiskReading:
    dimension: RiskDimension
    level: RiskLevel
    reason_ids: tuple[str, ...]
    field_ids: tuple[str, ...]
    template_id: str | None


@dataclass(frozen=True, slots=True)
class CapRecord:
    """An observed cap (RC-01..RC-04), recorded whether or not it binds."""

    rule_id: str
    ceiling: Stance
    binding: bool
    source_field_ids: tuple[str, ...]
    reason_id: str
    template_id: str


@dataclass(frozen=True, slots=True)
class CapUApplication:
    """Traceability record for one CAP-U application (methodology section 8)."""

    cap_source: str  # regime / derivatives / anomaly
    source_field_id: str  # the snapshot field that could not be read
    source_status: str  # always "not_evaluable"
    reason_id: str  # e.g. "CU-01:regime=not_evaluable"
    rule_id: str  # CU-01 / CU-02 / CU-03
    rule_ceiling: Stance
    applied_ceiling: Stance  # the least-permissive ceiling actually applied
    binding: bool  # whether this rule's own ceiling lowered the raw stance
    directional_stance_before_limits: Stance
    final_stance: Stance
    final_posture: Posture
    methodology_version: str
    parameter_version: str
    template_id: str


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One synthesized directional item, traceable to snapshot field ids."""

    domain: str
    direction: Direction
    strength: Strength
    band: str | None
    template_id: str | None
    field_ids: tuple[str, ...]
    raw_paths: tuple[str, ...]
    reason_ids: tuple[str, ...]
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    """The three-part explanation: what the evidence supported, what limited it, what is missing.
    All entries are template ids; a missing source is never described as bearish."""

    directional: tuple[str, ...]
    limits: tuple[str, ...]
    missing_context: tuple[str, ...]

    def all_template_ids(self) -> tuple[str, ...]:
        return self.directional + self.limits + self.missing_context


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    # -- identity / provenance (template_version is provenance, not identity)
    scope: str
    methodology_version: str
    parameter_version: str
    template_version: str
    snapshot_hash: str
    snapshot_as_of: str | None
    assumed_domain_score_versions: tuple[tuple[str, str], ...]
    observed_domain_score_versions: tuple[tuple[str, str], ...]
    # -- directional evidence
    tally: Tally
    expected_domains: int  # D from the scope definition
    coverage_available: int  # n (coverage is n / D)
    directional_stance_before_limits: Stance
    final_stance: Stance
    confidence: Confidence
    posture: Posture
    conflict: bool
    contradictions: tuple[str, ...]  # e.g. ("regime_disagrees",)
    # -- evidence lists
    supportive: tuple[EvidenceItem, ...]
    adverse: tuple[EvidenceItem, ...]
    neutral: tuple[EvidenceItem, ...]
    missing: tuple[str, ...]  # unavailable directional domains
    missing_context: tuple[str, ...]  # regime / derivatives / volatility_anomaly
    not_tracked: tuple[str, ...]
    readings: tuple[EvidenceReading, ...]  # every normalised reading (directional/risk/context)
    # -- risk
    risks: tuple[RiskReading, ...]
    max_risk: RiskLevel
    not_assessed_count: int
    # -- limits
    observed_caps: tuple[CapRecord, ...]
    cap_u: tuple[CapUApplication, ...]
    # -- confidence / posture / rule trace
    confidence_rule_ids: tuple[str, ...]
    posture_rule_id: str
    fired_rule_ids: tuple[str, ...]
    limitations: tuple[str, ...]  # template ids, e.g. LIMIT.derivatives_freshness
    explanation: Explanation
    snapshot_data_quality_state: str | None
    snapshot_has_conflicts: bool

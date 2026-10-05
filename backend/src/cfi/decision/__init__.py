"""L4.5 Deterministic Evidence Synthesis (Phase 38.2; ADR-0076).

Methodology: ``METHODOLOGY_DECISION_INTELLIGENCE.md``.

A pure, DB-free, network-free function over the stored snapshot payload:
``assess(snapshot_payload, scope, parameters) -> AssessmentResult``. No persistence, API, UI,
scheduling or model narration lives here (those are later, separately authorised phases).
"""

from cfi.decision.engine import assess, assess_extracted, risk_by_dimension, snapshot_hash
from cfi.decision.evidence import EvidenceReading, extract_evidence
from cfi.decision.result import AssessmentResult
from cfi.decision.universe import (
    METHODOLOGY_VERSION,
    PARAMETER_VERSION,
    PARAMETERS_V0,
    TEMPLATE_VERSION,
    Confidence,
    DecisionParameters,
    Posture,
    RiskLevel,
    Stance,
)

__all__ = [
    "METHODOLOGY_VERSION",
    "PARAMETERS_V0",
    "PARAMETER_VERSION",
    "TEMPLATE_VERSION",
    "AssessmentResult",
    "Confidence",
    "DecisionParameters",
    "EvidenceReading",
    "Posture",
    "RiskLevel",
    "Stance",
    "assess",
    "assess_extracted",
    "extract_evidence",
    "risk_by_dimension",
    "snapshot_hash",
]

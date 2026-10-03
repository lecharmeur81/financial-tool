"""The AI Analyst's structured, schema-validated response (Phase 21 spec, Sections 5-6, 11).

Field declaration order below IS the canonical section order (``cfi.analyst.universe.
RESPONSE_SECTIONS``) — every response this system serializes or stores presents the 12 sections in
this order by construction, regardless of what key order Claude's own JSON happened to use (a JSON
object's key order carries no semantic meaning, so enforcing a particular *incoming* order would be
enforcing something the format does not guarantee; see DECISIONS.md ADR-0068).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """One evidence bullet, grounded in the snapshot (R6): ``field_ids`` names every snapshot
    field this statement relies on. A statement with no ``field_ids`` may carry no numbers (the
    validator enforces this) — plain qualitative observations still need no citation."""

    model_config = ConfigDict(extra="forbid")

    text: str
    field_ids: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    """One non-predictive scenario (Phase 21 spec, Section 6): never a forecast, always evidence
    for, evidence against, and the conditions that would change the picture."""

    model_config = ConfigDict(extra="forbid")

    label: str
    description: str
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    strengthening_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)


class AnalystResponse(BaseModel):
    """The 12 required sections, in the user's own Phase 21 spec order (Section 5). Every field is
    required — a section with nothing to say still needs an explicit statement of that
    (``"Insufficient data."`` or similar), never a missing key (Section 5: "the schema must support
    these sections" for every question, even when a field is empty of findings)."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence: list[EvidenceItem]
    contradicting_evidence: list[EvidenceItem]
    market_regime: str
    key_changes: list[EvidenceItem]
    capital_participant_behavior: list[EvidenceItem]
    derivatives_liquidity_context: list[EvidenceItem]
    historical_context: list[EvidenceItem]
    risks_uncertainties: list[str]
    scenarios: list[Scenario]
    invalidation_conditions: list[str]
    data_quality: str

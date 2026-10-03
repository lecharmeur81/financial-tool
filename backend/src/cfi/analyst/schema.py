"""The AI Analyst's structured, schema-validated response (Phase 21 spec, Sections 5-6, 11; domain
structure correction ADR-0069).

Field declaration order below IS the canonical section order (``cfi.analyst.universe.
RESPONSE_SECTIONS``) — every response this system serializes or stores presents the 12 sections in
this order by construction, regardless of what key order Claude's own JSON happened to use (a JSON
object's key order carries no semantic meaning, so enforcing a particular *incoming* order would be
enforcing something the format does not guarantee; see DECISIONS.md ADR-0068).

ADR-0069: three of the 12 sections changed from a flat ``list[EvidenceItem]`` to a structured object
with one named list per intelligence domain it covers. The 12 top-level section names and their
order are unchanged — only the *type* of ``key_changes``, ``capital_participant_behavior`` and
``derivatives_liquidity_context`` changed, so that institutional/whale/retail behavior, derivatives/
liquidity context, and macro/market-structure/divergence/anomaly/capital-rotation findings are each
structurally identifiable rather than merged into an undifferentiated list that only the prompt (not
the schema) told Claude how to fill.
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


class ParticipantBehavior(BaseModel):
    """``capital_participant_behavior`` (ADR-0069): institutional, whale and retail findings kept
    structurally distinct rather than merged into one undifferentiated list. Each list still holds
    ordinary ``EvidenceItem``s, grounded in that domain's own snapshot fields (``cfi.analyst.
    universe.DOMAIN_TOOL_IDS``) — an empty list is a valid "nothing notable" answer; a domain whose
    underlying tool had no data must say ``"Insufficient data."`` rather than invent findings
    (enforced by ``cfi.analyst.validator``, not merely requested by the prompt)."""

    model_config = ConfigDict(extra="forbid")

    institutional: list[EvidenceItem]
    whale: list[EvidenceItem]
    retail: list[EvidenceItem]


class MarketContext(BaseModel):
    """``derivatives_liquidity_context`` (ADR-0069): derivatives and liquidity findings kept
    structurally distinct, same discipline as ``ParticipantBehavior`` above."""

    model_config = ConfigDict(extra="forbid")

    derivatives: list[EvidenceItem]
    liquidity: list[EvidenceItem]


class KeyChanges(BaseModel):
    """``key_changes`` (ADR-0069): the five intelligence domains that previously had no dedicated
    placement at all — macro, market structure, divergences, anomalies and capital rotation — each
    get their own named list here. "Key Changes" was already the platform's generic "what changed"
    bucket (CLAUDE.md R6 item 5); this just makes explicit which engine each change came from,
    instead of leaving it to an undifferentiated list the prompt alone described."""

    model_config = ConfigDict(extra="forbid")

    macro: list[EvidenceItem]
    market_structure: list[EvidenceItem]
    divergences: list[EvidenceItem]
    anomalies: list[EvidenceItem]
    capital_rotation: list[EvidenceItem]


class AnalystResponse(BaseModel):
    """The 12 required sections, in the user's own Phase 21 spec order (Section 5). Every field is
    required — a section with nothing to say still needs an explicit statement of that
    (``"Insufficient data."`` or similar), never a missing key (Section 5: "the schema must support
    these sections" for every question, even when a field is empty of findings).

    Three fields (``key_changes``, ``capital_participant_behavior``,
    ``derivatives_liquidity_context``) are structured per-domain objects rather than flat lists —
    see ``ParticipantBehavior``/``MarketContext``/``KeyChanges`` above and ADR-0069."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence: list[EvidenceItem]
    contradicting_evidence: list[EvidenceItem]
    market_regime: str
    key_changes: KeyChanges
    capital_participant_behavior: ParticipantBehavior
    derivatives_liquidity_context: MarketContext
    historical_context: list[EvidenceItem]
    risks_uncertainties: list[str]
    scenarios: list[Scenario]
    invalidation_conditions: list[str]
    data_quality: str

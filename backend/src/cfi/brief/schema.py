"""The Daily Market Brief's structured, schema-validated response (Phase 22 spec, Section 4).

This is a new, independent schema — it does NOT redesign ``cfi.analyst.schema.AnalystResponse``
(Section 2) — but it reuses the same per-item grounding shape Phase 21 already established
(``field_ids``, R6), extended with ``change_ids`` so a claimed *change* is always traceable to a
specific, computed ``cfi.brief.changes.FieldChange`` rather than asserted in prose alone.

Field declaration order below IS the canonical section order (``cfi.brief.universe.
RESPONSE_SECTIONS``) — the user's own literal 15-section list, in the order given.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BriefEvidenceItem(BaseModel):
    """One evidence bullet (same discipline as ``cfi.analyst.schema.EvidenceItem``, R6):
    ``field_ids`` grounds every number in ``text``. ``change_ids`` names the specific
    ``cfi.brief.changes.FieldChange``(s) that justify calling this a *change* since the previous
    brief — an item with an empty ``change_ids`` is an ordinary current-state observation, not a
    claimed change, and never requires a comparison basis to exist."""

    model_config = ConfigDict(extra="forbid")

    text: str
    field_ids: list[str] = Field(default_factory=list)
    change_ids: list[str] = Field(default_factory=list)


class MarketRegimeSection(BaseModel):
    """Section 4, item 2: current regime, its confidence, the evidence supporting that
    classification, and — only when a comparison basis exists (Section 5) — what changed versus
    the previous period."""

    model_config = ConfigDict(extra="forbid")

    current: str
    confidence: str
    evidence: list[BriefEvidenceItem] = Field(default_factory=list)
    changed_since_previous: list[BriefEvidenceItem] = Field(default_factory=list)


class BriefResponse(BaseModel):
    """The 15 required sections (Phase 22 spec, Section 4), in this exact order. Every field is
    required — a section with nothing to report still needs an explicit statement of that
    ("Insufficient data." or an empty list), never a missing key."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    market_regime: MarketRegimeSection
    institutional_activity: list[BriefEvidenceItem]
    whale_activity: list[BriefEvidenceItem]
    retail_activity: list[BriefEvidenceItem]
    derivatives_liquidity: list[BriefEvidenceItem]
    macro: list[BriefEvidenceItem]
    market_structure: list[BriefEvidenceItem]
    divergences_anomalies: list[BriefEvidenceItem]
    capital_rotation: list[BriefEvidenceItem]
    historical_context: list[BriefEvidenceItem]
    contradicting_evidence: list[BriefEvidenceItem]
    risks_uncertainties: list[str]
    what_to_monitor: list[str]
    data_quality: str

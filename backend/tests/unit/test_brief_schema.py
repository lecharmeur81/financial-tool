"""`BriefResponse`'s shape (Phase 22 spec, Section 4): exactly 15 top-level sections, in order,
`extra="forbid"` everywhere, and the shared `BriefEvidenceItem`/`change_ids` discipline."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cfi.brief.schema import BriefEvidenceItem, BriefResponse, MarketRegimeSection
from cfi.brief.universe import RESPONSE_SECTIONS

MINIMAL = {
    "executive_summary": "Insufficient data.",
    "market_regime": {
        "current": "Insufficient data.",
        "confidence": "Insufficient data.",
        "evidence": [],
        "changed_since_previous": [],
    },
    "institutional_activity": [],
    "whale_activity": [],
    "retail_activity": [],
    "derivatives_liquidity": [],
    "macro": [],
    "market_structure": [],
    "divergences_anomalies": [],
    "capital_rotation": [],
    "historical_context": [],
    "contradicting_evidence": [],
    "risks_uncertainties": [],
    "what_to_monitor": [],
    "data_quality": "Insufficient data.",
}


def test_response_sections_tuple_has_exactly_15_names_matching_the_schema_field_order() -> None:
    assert len(RESPONSE_SECTIONS) == 15
    assert tuple(BriefResponse.model_fields.keys()) == RESPONSE_SECTIONS


def test_minimal_response_validates() -> None:
    response = BriefResponse.model_validate(MINIMAL)
    assert response.executive_summary == "Insufficient data."
    assert response.market_regime.current == "Insufficient data."


def test_unknown_top_level_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BriefResponse.model_validate({**MINIMAL, "extra_section": []})


def test_a_required_section_cannot_be_omitted() -> None:
    bad = {k: v for k, v in MINIMAL.items() if k != "capital_rotation"}
    with pytest.raises(ValidationError):
        BriefResponse.model_validate(bad)


def test_evidence_item_defaults_to_empty_field_ids_and_change_ids() -> None:
    item = BriefEvidenceItem.model_validate({"text": "Observed value."})
    assert item.field_ids == []
    assert item.change_ids == []


def test_evidence_item_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        BriefEvidenceItem.model_validate({"text": "x", "confidence": "high"})


def test_market_regime_section_round_trips_evidence_and_changes() -> None:
    section = MarketRegimeSection.model_validate(
        {
            "current": "leveraged expansion",
            "confidence": "0.6",
            "evidence": [{"text": "regime text", "field_ids": ["get_market_regime.label"]}],
            "changed_since_previous": [
                {
                    "text": "regime flipped",
                    "field_ids": ["get_market_regime.label"],
                    "change_ids": ["chg.get_market_regime.label"],
                }
            ],
        }
    )
    assert section.evidence[0].field_ids == ["get_market_regime.label"]
    assert section.changed_since_previous[0].change_ids == ["chg.get_market_regime.label"]

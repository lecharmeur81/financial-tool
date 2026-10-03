"""``AnalystResponse`` (Phase 21, Section 5-6): the 12 required sections, and ``extra="forbid"``
so a stray key from Claude fails validation loudly rather than being silently dropped or ignored.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cfi.analyst.schema import AnalystResponse, Scenario

MINIMAL = {
    "summary": "Insufficient data.",
    "evidence": [],
    "contradicting_evidence": [],
    "market_regime": "Insufficient data.",
    "key_changes": [],
    "capital_participant_behavior": [],
    "derivatives_liquidity_context": [],
    "historical_context": [],
    "risks_uncertainties": [],
    "scenarios": [],
    "invalidation_conditions": [],
    "data_quality": "Insufficient data.",
}


def test_minimal_response_validates() -> None:
    response = AnalystResponse.model_validate(MINIMAL)
    assert response.summary == "Insufficient data."
    assert response.evidence == []


def test_missing_required_section_is_rejected() -> None:
    payload = dict(MINIMAL)
    del payload["scenarios"]
    with pytest.raises(ValidationError):
        AnalystResponse.model_validate(payload)


def test_extra_top_level_key_is_rejected() -> None:
    payload = {**MINIMAL, "confidence_score": 0.8}
    with pytest.raises(ValidationError):
        AnalystResponse.model_validate(payload)


def test_evidence_item_extra_key_is_rejected() -> None:
    payload = {
        **MINIMAL,
        "evidence": [
            {"text": "BTC is up.", "field_ids": ["get_market_data.assets.BTC"], "prob": 0.9}
        ],
    }
    with pytest.raises(ValidationError):
        AnalystResponse.model_validate(payload)


def test_scenario_shape() -> None:
    payload = {
        **MINIMAL,
        "scenarios": [
            {
                "label": "Continued absorption",
                "description": "Institutional buying continues to absorb retail selling.",
                "supporting_evidence": [{"text": "x", "field_ids": []}],
                "contradicting_evidence": [],
                "strengthening_conditions": ["ETF flows stay positive."],
                "invalidation_conditions": ["ETF flows turn net negative for 5 consecutive days."],
            }
        ],
    }
    response = AnalystResponse.model_validate(payload)
    assert response.scenarios[0].label == "Continued absorption"
    # Non-predictive by construction: the schema has no probability field to assign one to.
    assert "probability" not in Scenario.model_fields

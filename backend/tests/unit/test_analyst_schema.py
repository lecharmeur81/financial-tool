"""``AnalystResponse`` (Phase 21, Section 5-6): the 12 required sections, and ``extra="forbid"``
so a stray key from Claude fails validation loudly rather than being silently dropped or ignored.

Domain structure correction (ADR-0069): ``key_changes``, ``capital_participant_behavior`` and
``derivatives_liquidity_context`` are structured per-domain objects, not flat lists — see
``test_domain_structure.py``-equivalent coverage below for the 10 intelligence domains.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cfi.analyst.schema import (
    AnalystResponse,
    KeyChanges,
    MarketContext,
    ParticipantBehavior,
    Scenario,
)

EMPTY_PARTICIPANT_BEHAVIOR: dict[str, list[object]] = {
    "institutional": [],
    "whale": [],
    "retail": [],
}
EMPTY_MARKET_CONTEXT: dict[str, list[object]] = {"derivatives": [], "liquidity": []}
EMPTY_KEY_CHANGES: dict[str, list[object]] = {
    "macro": [],
    "market_structure": [],
    "divergences": [],
    "anomalies": [],
    "capital_rotation": [],
}

MINIMAL = {
    "summary": "Insufficient data.",
    "evidence": [],
    "contradicting_evidence": [],
    "market_regime": "Insufficient data.",
    "key_changes": EMPTY_KEY_CHANGES,
    "capital_participant_behavior": EMPTY_PARTICIPANT_BEHAVIOR,
    "derivatives_liquidity_context": EMPTY_MARKET_CONTEXT,
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


def test_institutional_whale_and_retail_evidence_remain_distinguishable() -> None:
    """ADR-0069 correction #1: these three domains must not be merged into one list."""
    payload = {
        **MINIMAL,
        "capital_participant_behavior": {
            "institutional": [{"text": "ETF inflows positive.", "field_ids": []}],
            "whale": [{"text": "Large wallets accumulating.", "field_ids": []}],
            "retail": [{"text": "Retail speculation elevated.", "field_ids": []}],
        },
    }
    response = AnalystResponse.model_validate(payload)
    assert response.capital_participant_behavior.institutional[0].text == "ETF inflows positive."
    assert response.capital_participant_behavior.whale[0].text == "Large wallets accumulating."
    assert response.capital_participant_behavior.retail[0].text == "Retail speculation elevated."


def test_participant_behavior_requires_all_three_domain_keys() -> None:
    payload = {**MINIMAL, "capital_participant_behavior": {"institutional": [], "whale": []}}
    with pytest.raises(ValidationError):
        AnalystResponse.model_validate(payload)


def test_derivatives_and_liquidity_evidence_remain_distinguishable() -> None:
    """ADR-0069 correction #2: these two domains must not be merged into one list."""
    payload = {
        **MINIMAL,
        "derivatives_liquidity_context": {
            "derivatives": [{"text": "Funding elevated.", "field_ids": []}],
            "liquidity": [{"text": "Stablecoin supply growing.", "field_ids": []}],
        },
    }
    response = AnalystResponse.model_validate(payload)
    assert response.derivatives_liquidity_context.derivatives[0].text == "Funding elevated."
    assert response.derivatives_liquidity_context.liquidity[0].text == "Stablecoin supply growing."


def test_additional_intelligence_domains_each_have_structured_placement() -> None:
    """ADR-0069 correction #2: these five domains previously had no dedicated placement at all."""
    payload = {
        **MINIMAL,
        "key_changes": {
            "macro": [{"text": "Yield curve steepening.", "field_ids": []}],
            "market_structure": [{"text": "BTC dominance rising.", "field_ids": []}],
            "divergences": [{"text": "Institutional/retail divergence detected.", "field_ids": []}],
            "anomalies": [{"text": "Funding rate at an anomalous percentile.", "field_ids": []}],
            "capital_rotation": [{"text": "Possible rotation BTC to SOL.", "field_ids": []}],
        },
    }
    response = AnalystResponse.model_validate(payload)
    assert response.key_changes.macro[0].text == "Yield curve steepening."
    assert response.key_changes.market_structure[0].text == "BTC dominance rising."
    assert response.key_changes.divergences[0].text == "Institutional/retail divergence detected."
    assert response.key_changes.anomalies[0].text == "Funding rate at an anomalous percentile."
    assert response.key_changes.capital_rotation[0].text == "Possible rotation BTC to SOL."


def test_key_changes_requires_all_five_domain_keys() -> None:
    payload = {**MINIMAL, "key_changes": {"macro": [], "market_structure": []}}
    with pytest.raises(ValidationError):
        AnalystResponse.model_validate(payload)


def test_response_still_has_exactly_the_original_12_top_level_sections() -> None:
    """ADR-0069 correction: the 12 top-level section names and order are unchanged — only the
    *type* of three of them changed, from a flat list to a structured per-domain object."""
    from cfi.analyst.universe import RESPONSE_SECTIONS

    assert list(AnalystResponse.model_fields.keys()) == list(RESPONSE_SECTIONS)
    assert list(ParticipantBehavior.model_fields.keys()) == ["institutional", "whale", "retail"]
    assert list(MarketContext.model_fields.keys()) == ["derivatives", "liquidity"]
    assert list(KeyChanges.model_fields.keys()) == [
        "macro",
        "market_structure",
        "divergences",
        "anomalies",
        "capital_rotation",
    ]

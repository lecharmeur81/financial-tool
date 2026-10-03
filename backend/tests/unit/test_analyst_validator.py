"""Deterministic validation of Claude's structured output against its own snapshot (Phase 21,
Sections 4/11/12; domain structure correction ADR-0069). Every failure mode in the user's own
Section 12 test list gets its own test: an invented number, an unsupported directional verdict, a
rotation hypothesis stated as fact, a historical-similarity guarantee, and a missing "Insufficient
data."/"Sources conflict." phrase — plus (ADR-0069) a claim about a domain whose own tool had no
data in the snapshot, and a field_id cited from the wrong domain's tool.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from cfi.analyst.schema import AnalystResponse
from cfi.analyst.snapshot import Snapshot, SnapshotField
from cfi.analyst.validator import validate

AS_OF = datetime(2026, 9, 28, tzinfo=UTC)

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
    "summary": "Summary text.",
    "evidence": [],
    "contradicting_evidence": [],
    "market_regime": "Regime text.",
    "key_changes": EMPTY_KEY_CHANGES,
    "capital_participant_behavior": EMPTY_PARTICIPANT_BEHAVIOR,
    "derivatives_liquidity_context": EMPTY_MARKET_CONTEXT,
    "historical_context": [],
    "risks_uncertainties": [],
    "scenarios": [],
    "invalidation_conditions": [],
    "data_quality": "All good.",
}


def _snapshot(
    fields: list[SnapshotField],
    *,
    data_quality_state: str = "ok",
    has_conflicts: bool = False,
    raw: dict[str, Any] | None = None,
) -> Snapshot:
    return Snapshot(
        snapshot_id="abc123",
        snapshot_version="analyst_snapshot.v1",
        created_at=AS_OF,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question=None,
        tools_called=[],
        fields=fields,
        field_index={f.field_id: f for f in fields},
        raw=raw or {},
        data_quality_state=data_quality_state,
        has_conflicts=has_conflicts,
    )


def _field(field_id: str, display: str) -> SnapshotField:
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal(display)
    except InvalidOperation:
        value = None
    return SnapshotField(field_id=field_id, display=display, value=value)


@pytest.fixture
def btc_price_snapshot() -> Snapshot:
    return _snapshot([_field("get_market_data.assets.BTC.price_close", "65000.00")])


def test_grounded_evidence_citing_the_exact_display_value_passes(
    btc_price_snapshot: Snapshot,
) -> None:
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "evidence": [
                {
                    "text": "BTC last traded at 65000.00.",
                    "field_ids": ["get_market_data.assets.BTC.price_close"],
                }
            ],
        }
    )
    result = validate(response, btc_price_snapshot)
    assert result.ok, result.errors


def test_invented_number_fails_grounding(btc_price_snapshot: Snapshot) -> None:
    """A number nowhere in the snapshot must never be accepted (R6): this is the "missing data"
    scenario — the analyst may not invent an institutional flow figure it was never given."""
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "evidence": [
                {
                    "text": "Institutional ETF inflows reached 1200 BTC today.",
                    "field_ids": ["get_market_data.assets.BTC.price_close"],
                }
            ],
        }
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("1200" in e for e in result.errors)


def test_number_cited_against_the_wrong_field_id_fails(btc_price_snapshot: Snapshot) -> None:
    """Citing a real snapshot number, but under an unrelated field_id, still fails — the citation
    itself must be honest, not just the number's mere presence somewhere in the snapshot."""
    other = _snapshot(
        [
            _field("get_market_data.assets.BTC.price_close", "65000.00"),
            _field("get_market_data.assets.ETH.price_close", "3200.00"),
        ]
    )
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "evidence": [
                {
                    "text": "ETH is at 65000.00.",
                    "field_ids": ["get_market_data.assets.ETH.price_close"],
                }
            ],
        }
    )
    result = validate(response, other)
    assert not result.ok


def test_unknown_field_id_is_flagged(btc_price_snapshot: Snapshot) -> None:
    response = AnalystResponse.model_validate(
        {**MINIMAL, "evidence": [{"text": "BTC context.", "field_ids": ["no_such_field"]}]}
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("unknown field_id" in e for e in result.errors)


def test_bullish_bearish_verdict_is_banned(btc_price_snapshot: Snapshot) -> None:
    """No manufactured directional certainty from mixed/ambiguous evidence (Section 12)."""
    response = AnalystResponse.model_validate({**MINIMAL, "summary": "The market looks bullish."})
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("verdict_language" in e for e in result.errors)


def test_trading_directive_is_banned(btc_price_snapshot: Snapshot) -> None:
    response = AnalystResponse.model_validate(
        {**MINIMAL, "risks_uncertainties": ["You should buy now before it moves further."]}
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("directive_language" in e for e in result.errors)


def test_capital_moved_from_x_to_y_is_treated_as_fact_not_hypothesis(
    btc_price_snapshot: Snapshot,
) -> None:
    """An inferred rotation must stay a hedged hypothesis (Phase 20's own classify_edge
    discipline) — the analyst's prose must not undo that hedge by asserting it as observed."""
    response = AnalystResponse.model_validate(
        {**MINIMAL, "market_regime": "Capital has moved from ETH to SOL this week."}
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("observed fact" in e for e in result.errors)


def test_historical_similarity_guarantee_is_banned(btc_price_snapshot: Snapshot) -> None:
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "historical_context": [{"text": "History always repeats itself.", "field_ids": []}],
        }
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("history_guarantee_language" in e for e in result.errors)


def test_insufficient_data_phrase_required_when_snapshot_says_so(
    btc_price_snapshot: Snapshot,
) -> None:
    insufficient = _snapshot([], data_quality_state="insufficient")
    response = AnalystResponse.model_validate({**MINIMAL, "data_quality": "Everything looks fine."})
    result = validate(response, insufficient)
    assert not result.ok
    assert any("Insufficient data." in e for e in result.errors)

    ok_response = AnalystResponse.model_validate({**MINIMAL, "data_quality": "Insufficient data."})
    assert validate(ok_response, insufficient).ok


def test_sources_conflict_phrase_required_when_snapshot_has_conflicts(
    btc_price_snapshot: Snapshot,
) -> None:
    conflicting = _snapshot([], has_conflicts=True)
    response = AnalystResponse.model_validate({**MINIMAL, "data_quality": "Everything looks fine."})
    result = validate(response, conflicting)
    assert not result.ok
    assert any("Sources conflict." in e for e in result.errors)

    ok_response = AnalystResponse.model_validate(
        {**MINIMAL, "data_quality": "Sources conflict. Institutional and whale flows disagree."}
    )
    assert validate(ok_response, conflicting).ok


def test_scenario_evidence_and_conditions_are_validated_too(btc_price_snapshot: Snapshot) -> None:
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "scenarios": [
                {
                    "label": "A",
                    "description": "This is bullish for BTC.",
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "strengthening_conditions": [],
                    "invalidation_conditions": [],
                }
            ],
        }
    )
    result = validate(response, btc_price_snapshot)
    assert not result.ok
    assert any("scenarios[0].description" in e for e in result.errors)


def test_clean_response_with_no_findings_is_ok(btc_price_snapshot: Snapshot) -> None:
    response = AnalystResponse.model_validate(MINIMAL)
    assert validate(response, btc_price_snapshot).ok


# --------------------------------------------------------------------------- ADR-0069: domain
# structure correction — each of the 10 intelligence domains validated independently.


def _ok_result(tool_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"tool_id": tool_id, "status": "ok", "data": data, "error": None}


def _unavailable_result(tool_id: str) -> dict[str, Any]:
    return {"tool_id": tool_id, "status": "unavailable", "data": None, "error": None}


def test_all_five_additional_intelligence_domains_each_have_structured_placement() -> None:
    """Macro, market structure, divergences, anomalies and capital rotation (previously no
    dedicated placement at all) each validate correctly when citing their own tool's field."""
    fields = [
        _field("get_macro.yield_curve", "1.25"),
        _field("get_market_structure.btc_dominance", "54.3"),
        _field("calculate_divergence.pairs[0].value", "0.72"),
        _field("get_anomalies.readings[0].percentile", "97.5"),
        _field("get_capital_rotation.matrix[0].share_delta", "2.1"),
    ]
    snapshot = _snapshot(
        fields,
        raw={
            "get_macro": _ok_result("get_macro", {}),
            "get_market_structure": _ok_result("get_market_structure", {}),
            "calculate_divergence": _ok_result("calculate_divergence", {}),
            "get_anomalies": _ok_result("get_anomalies", {}),
            "get_capital_rotation": _ok_result("get_capital_rotation", {}),
        },
    )
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "key_changes": {
                "macro": [{"text": "Yield curve at 1.25.", "field_ids": ["get_macro.yield_curve"]}],
                "market_structure": [
                    {
                        "text": "BTC dominance at 54.3.",
                        "field_ids": ["get_market_structure.btc_dominance"],
                    }
                ],
                "divergences": [
                    {
                        "text": "Divergence reading 0.72.",
                        "field_ids": ["calculate_divergence.pairs[0].value"],
                    }
                ],
                "anomalies": [
                    {
                        "text": "Anomaly at the 97.5 percentile.",
                        "field_ids": ["get_anomalies.readings[0].percentile"],
                    }
                ],
                "capital_rotation": [
                    {
                        "text": "Share delta of 2.1.",
                        "field_ids": ["get_capital_rotation.matrix[0].share_delta"],
                    }
                ],
            },
        }
    )
    result = validate(response, snapshot)
    assert result.ok, result.errors


def test_institutional_whale_and_retail_remain_independently_grounded() -> None:
    fields = [
        _field("get_institutional_flows.score", "0.80"),
        _field("get_whale_activity.score", "0.40"),
        _field("get_retail_activity.score", "0.60"),
    ]
    snapshot = _snapshot(
        fields,
        raw={
            "get_institutional_flows": _ok_result("get_institutional_flows", {}),
            "get_whale_activity": _ok_result("get_whale_activity", {}),
            "get_retail_activity": _ok_result("get_retail_activity", {}),
        },
    )
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "capital_participant_behavior": {
                "institutional": [
                    {
                        "text": "Institutional score 0.80.",
                        "field_ids": ["get_institutional_flows.score"],
                    }
                ],
                "whale": [{"text": "Whale score 0.40.", "field_ids": ["get_whale_activity.score"]}],
                "retail": [
                    {"text": "Retail score 0.60.", "field_ids": ["get_retail_activity.score"]}
                ],
            },
        }
    )
    assert validate(response, snapshot).ok


def test_derivatives_and_liquidity_remain_independently_grounded() -> None:
    fields = [_field("get_derivatives.score", "0.55"), _field("get_liquidity.score", "0.70")]
    snapshot = _snapshot(
        fields,
        raw={
            "get_derivatives": _ok_result("get_derivatives", {}),
            "get_liquidity": _ok_result("get_liquidity", {}),
        },
    )
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "derivatives_liquidity_context": {
                "derivatives": [
                    {"text": "Derivatives score 0.55.", "field_ids": ["get_derivatives.score"]}
                ],
                "liquidity": [
                    {"text": "Liquidity score 0.70.", "field_ids": ["get_liquidity.score"]}
                ],
            },
        }
    )
    assert validate(response, snapshot).ok


def test_citing_a_different_domains_field_id_fails(btc_price_snapshot: Snapshot) -> None:
    """A whale field_id cited inside the "institutional" bucket must fail — a domain's evidence
    may only cite that domain's own tool (ADR-0069)."""
    fields = [
        _field("get_institutional_flows.score", "0.80"),
        _field("get_whale_activity.score", "0.40"),
    ]
    snapshot = _snapshot(
        fields,
        raw={
            "get_institutional_flows": _ok_result("get_institutional_flows", {}),
            "get_whale_activity": _ok_result("get_whale_activity", {}),
        },
    )
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "capital_participant_behavior": {
                "institutional": [
                    {"text": "Score 0.40.", "field_ids": ["get_whale_activity.score"]}
                ],
                "whale": [],
                "retail": [],
            },
        }
    )
    result = validate(response, snapshot)
    assert not result.ok
    assert any("get_whale_activity" in e and "institutional" in e for e in result.errors)


def test_missing_domain_data_without_insufficient_data_phrase_fails() -> None:
    """A domain whose own tool is unavailable: Claude may not simply claim to have analyzed it
    (ADR-0069) — this is the "cannot claim to have analyzed a domain when data was not available"
    requirement."""
    snapshot = _snapshot([], raw={"get_macro": _unavailable_result("get_macro")})
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "key_changes": {
                **EMPTY_KEY_CHANGES,
                "macro": [{"text": "Macro conditions are supportive.", "field_ids": []}],
            },
        }
    )
    result = validate(response, snapshot)
    assert not result.ok
    assert any("macro" in e and "no data in this snapshot" in e for e in result.errors)


def test_missing_domain_data_with_insufficient_data_phrase_passes() -> None:
    snapshot = _snapshot([], raw={"get_macro": _unavailable_result("get_macro")})
    response = AnalystResponse.model_validate(
        {
            **MINIMAL,
            "key_changes": {
                **EMPTY_KEY_CHANGES,
                "macro": [{"text": "Insufficient data.", "field_ids": []}],
            },
        }
    )
    assert validate(response, snapshot).ok


def test_missing_domain_data_with_empty_list_is_ok_not_required_to_fabricate() -> None:
    """Section 5: not every domain needs a finding for every question — an empty list for an
    unavailable domain is a valid answer, never required to produce filler content (ADR-0069's
    "do not require fabricated content for missing domains")."""
    snapshot = _snapshot([], raw={"get_macro": _unavailable_result("get_macro")})
    response = AnalystResponse.model_validate(MINIMAL)  # key_changes.macro == []
    assert validate(response, snapshot).ok

"""Deterministic validation of Claude's structured output against its own snapshot (Phase 21,
Sections 4/11/12). Every failure mode in the user's own Section 12 test list gets its own test:
an invented number, an unsupported directional verdict, a rotation hypothesis stated as fact, a
historical-similarity guarantee, and a missing "Insufficient data."/"Sources conflict." phrase.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cfi.analyst.schema import AnalystResponse
from cfi.analyst.snapshot import Snapshot, SnapshotField
from cfi.analyst.validator import validate

AS_OF = datetime(2026, 9, 28, tzinfo=UTC)

MINIMAL = {
    "summary": "Summary text.",
    "evidence": [],
    "contradicting_evidence": [],
    "market_regime": "Regime text.",
    "key_changes": [],
    "capital_participant_behavior": [],
    "derivatives_liquidity_context": [],
    "historical_context": [],
    "risks_uncertainties": [],
    "scenarios": [],
    "invalidation_conditions": [],
    "data_quality": "All good.",
}


def _snapshot(
    fields: list[SnapshotField], *, data_quality_state: str = "ok", has_conflicts: bool = False
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
        raw={},
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

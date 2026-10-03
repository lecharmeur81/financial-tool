"""Deterministic validation of the Daily Brief against its own snapshot and `ChangeSet` (Phase 22
spec, Sections 5-7, 10/11). Every failure mode in the spec's Section 11 test list gets a case: an
invented number, a banned directive/position-sizing/price-target phrase, a rotation hypothesis
stated as fact, a change_id cited with no comparison basis or an unknown change_id, a field cited
from the wrong section's domain tool, and a missing "Insufficient data."/"Sources conflict."
disclosure."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.analyst.snapshot import Snapshot, SnapshotField
from cfi.brief.changes import ChangeSet, FieldChange
from cfi.brief.schema import BriefResponse
from cfi.brief.validator import validate
from tests.unit.test_brief_schema import MINIMAL

AS_OF = datetime(2026, 9, 29, tzinfo=UTC)
MINIMAL_MARKET_REGIME: dict[str, Any] = MINIMAL["market_regime"]  # type: ignore[assignment]


def _field(field_id: str, display: str) -> SnapshotField:
    try:
        value = Decimal(display)
    except InvalidOperation:
        value = None
    return SnapshotField(field_id=field_id, display=display, value=value)


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


def _changes(changes: list[FieldChange] | None = None, basis: str = "none") -> ChangeSet:
    changes = changes or []
    return ChangeSet(
        comparison_basis=basis,  # type: ignore[arg-type]
        changes=changes,
        change_index={c.change_id: c for c in changes},
    )


def _response(**overrides: Any) -> BriefResponse:
    return BriefResponse.model_validate({**MINIMAL, **overrides})


def test_minimal_response_with_no_snapshot_data_and_no_previous_brief_is_valid() -> None:
    result = validate(_response(), _snapshot([]), _changes())
    assert result.ok, result.errors


def test_grounded_number_in_an_evidence_item_passes() -> None:
    field = _field("get_macro.dxy", "104.2")
    response = _response(
        macro=[{"text": "DXY is at 104.2.", "field_ids": ["get_macro.dxy"], "change_ids": []}]
    )
    result = validate(response, _snapshot([field]), _changes())
    assert result.ok, result.errors


def test_invented_number_is_rejected() -> None:
    field = _field("get_macro.dxy", "104.2")
    response = _response(
        macro=[{"text": "DXY is at 999.9.", "field_ids": ["get_macro.dxy"], "change_ids": []}]
    )
    result = validate(response, _snapshot([field]), _changes())
    assert not result.ok
    assert any("999.9" in e for e in result.errors)


def test_unknown_field_id_is_rejected() -> None:
    response = _response(
        macro=[
            {
                "text": "No number here.",
                "field_ids": ["get_macro.nonexistent"],
                "change_ids": [],
            }
        ]
    )
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("unknown field_id" in e for e in result.errors)


def test_field_id_from_the_wrong_sections_domain_tool_is_rejected() -> None:
    field = _field("get_whale_activity.exchange_inflow", "120")
    response = _response(
        macro=[{"text": "No number.", "field_ids": ["get_whale_activity.exchange_inflow"]}]
    )
    result = validate(response, _snapshot([field]), _changes())
    assert not result.ok
    assert any("outside this section's own domain tool" in e for e in result.errors)


def test_change_id_cited_with_no_comparison_basis_is_rejected() -> None:
    response = _response(
        capital_rotation=[{"text": "Share moved.", "change_ids": ["chg.get_capital_rotation.x"]}]
    )
    result = validate(response, _snapshot([]), _changes(basis="none"))
    assert not result.ok
    assert any("no previous brief to compare against" in e for e in result.errors)


def test_unknown_change_id_with_a_valid_comparison_basis_is_rejected() -> None:
    response = _response(
        capital_rotation=[{"text": "Share moved.", "change_ids": ["chg.does_not_exist"]}]
    )
    result = validate(response, _snapshot([]), _changes(basis="previous_brief"))
    assert not result.ok
    assert any("unknown change_id" in e for e in result.errors)


def test_real_change_id_from_a_valid_comparison_basis_passes() -> None:
    change = FieldChange(
        change_id="chg.get_capital_rotation.share_delta",
        field_id="get_capital_rotation.share_delta",
        previous_display="0.10",
        current_display="0.15",
        delta="0.05",
    )
    field = _field("get_capital_rotation.share_delta", "0.15")
    response = _response(
        capital_rotation=[
            {
                "text": "Share moved to 0.15.",
                "field_ids": ["get_capital_rotation.share_delta"],
                "change_ids": ["chg.get_capital_rotation.share_delta"],
            }
        ]
    )
    result = validate(response, _snapshot([field]), _changes([change], basis="previous_brief"))
    assert result.ok, result.errors


def test_rotation_presented_as_observed_fact_is_rejected() -> None:
    response = _response(capital_rotation=[{"text": "Capital moved from ETH to SOL this week."}])
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("observed fact" in e for e in result.errors)


def test_long_short_position_directive_is_rejected() -> None:
    response = _response(executive_summary="Traders should take a long position now.")
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("brief_directive_language" in e for e in result.errors)


def test_position_sizing_instruction_is_rejected() -> None:
    response = _response(what_to_monitor=["Risk 2% of capital per trade on this setup."])
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("brief_position_sizing_language" in e for e in result.errors)


def test_price_target_presented_as_certainty_is_rejected() -> None:
    response = _response(executive_summary="BTC will reach $150000 by year end.")
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("brief_price_target_certainty_language" in e for e in result.errors)


def test_bullish_bearish_verdict_is_rejected() -> None:
    response = _response(market_regime={**MINIMAL_MARKET_REGIME, "current": "bullish regime"})
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("verdict_language" in e for e in result.errors)


def test_history_guarantee_language_in_historical_context_is_rejected() -> None:
    response = _response(
        historical_context=[{"text": "History always repeats itself, so this will happen again."}]
    )
    result = validate(response, _snapshot([]), _changes())
    assert not result.ok
    assert any("history_guarantee_language" in e for e in result.errors)


def test_missing_insufficient_data_phrase_when_snapshot_state_is_insufficient_is_rejected() -> None:
    response = _response(data_quality="Everything looks fine.")
    result = validate(response, _snapshot([], data_quality_state="insufficient"), _changes())
    assert not result.ok
    assert any("Insufficient data." in e for e in result.errors)


def test_missing_sources_conflict_phrase_when_snapshot_has_conflicts_is_rejected() -> None:
    response = _response(data_quality="Everything looks fine.")
    result = validate(response, _snapshot([], has_conflicts=True), _changes())
    assert not result.ok
    assert any("Sources conflict." in e for e in result.errors)


def test_insufficient_data_phrase_satisfies_the_insufficient_state_requirement() -> None:
    response = _response(data_quality="Insufficient data. for the macro domain today.")
    result = validate(response, _snapshot([], data_quality_state="insufficient"), _changes())
    assert result.ok, result.errors


def test_market_regime_changed_since_previous_without_a_comparison_basis_is_rejected() -> None:
    response = _response(
        market_regime={
            **MINIMAL_MARKET_REGIME,
            "changed_since_previous": [{"text": "Regime flipped."}],
        }
    )
    result = validate(response, _snapshot([]), _changes(basis="none"))
    assert not result.ok
    assert any("no previous brief exists" in e for e in result.errors)

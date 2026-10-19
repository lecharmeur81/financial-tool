"""Phase 52 P3: the derived lifecycle marker (pure, database-free).

Covers the five kinds, the separation of "ended" from "cannot be evaluated" from "still holds",
terminal-status handling, unreadable snapshots and the no-write guarantee."""

from __future__ import annotations

from typing import Any

import pytest

from cfi.alerts.lifecycle_marker import (
    FLAGGED_STATE_TYPES,
    build_current_evaluation,
    derive_marker,
)
from cfi.alerts.service import _FLAGGED_STATE_TYPES
from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS

INST = ALERT_TYPE_TOOL_IDS["institutional_flow"]
DIV = ALERT_TYPE_TOOL_IDS["divergence"]


def _payload(tool_results: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_version": "analyst_snapshot.v1",
        "as_of": "2026-10-19T08:00:00+00:00",
        "knowledge_time": "2026-10-19T08:00:00+00:00",
        "tools_called": list(tool_results),
        "data_quality_state": "ok",
        "has_conflicts": False,
        "tool_results": tool_results,
    }


def _inst(band: str | None, status: str = "ok") -> dict[str, Any]:
    score = {"status": status, "band": band}
    return {INST: {"status": "ok", "data": {"assets": [{"asset": "BTC", "score": score}]}}}


def _div(divergent: bool) -> dict[str, Any]:
    comparison = {
        "comparison_id": "c1",
        "asset": "BTC",
        "title": "t",
        "is_divergent": divergent,
        "observed_quadrant": "q1",
        "metric_a": {"data_quality": {"status": "ok"}},
        "metric_b": {"data_quality": {"status": "ok"}},
    }
    return {DIV: {"status": "ok", "data": {"comparisons": [comparison]}}}


def _alert(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": "active",
        "alert_type": "institutional_flow",
        "dedup_key": "institutional_flow:BTC",
        "observed_value": "strong",
        "source_tool_id": INST,
    }
    row.update(over)
    return row


def _marker(alert: dict[str, Any], tool_results: dict[str, Any] | None) -> Any:
    current = None if tool_results is None else build_current_evaluation(7, _payload(tool_results))
    return derive_marker(alert, current)


def test_flagged_types_match_the_service() -> None:
    assert set(FLAGGED_STATE_TYPES) == set(_FLAGGED_STATE_TYPES)


def test_still_holds_when_the_same_value_is_current() -> None:
    m = _marker(_alert(), _inst("strong"))
    assert m.kind == "still_holds"
    assert m.evaluated_snapshot_id == 7
    assert m.evaluated_as_of == "2026-10-19T08:00:00+00:00"


def test_state_ended_when_the_value_moved_and_it_is_not_called_invalid() -> None:
    m = _marker(_alert(), _inst("weak"))
    assert m.kind == "state_ended"
    assert "not invalidated" in m.reason


def test_flagged_alert_ends_when_the_flag_is_no_longer_positive() -> None:
    alert = _alert(
        alert_type="divergence",
        dedup_key="divergence:c1",
        observed_value="q1",
        source_tool_id=DIV,
    )
    assert _marker(alert, _div(True)).kind == "still_holds"
    ended = _marker(alert, _div(False))
    assert ended.kind == "state_ended"
    assert "explicitly" in ended.reason


def test_flagged_alert_with_an_absent_item_or_unknown_reading_is_not_ended() -> None:
    alert = _alert(
        alert_type="divergence",
        dedup_key="divergence:c1",
        observed_value="q1",
        source_tool_id=DIV,
    )
    empty = {DIV: {"status": "ok", "data": {"comparisons": []}}}
    unavailable = _div(False)
    unavailable[DIV]["data"]["comparisons"][0]["is_divergent"] = None
    for results in (empty, unavailable):
        assert _marker(alert, results).kind == "cannot_be_evaluated"


def test_flagged_alert_is_not_ended_when_its_tool_gave_no_result() -> None:
    alert = _alert(
        alert_type="divergence",
        dedup_key="divergence:c1",
        observed_value="q1",
        source_tool_id=DIV,
    )
    failed = {DIV: {"status": "error", "data": None}}
    absent: dict[str, Any] = {}
    for results in (failed, absent):
        m = _marker(alert, results)
        assert m.kind == "cannot_be_evaluated"
        assert "not ended" in m.reason


@pytest.mark.parametrize("status", ["insufficient_data", "unavailable", "not_applicable"])
def test_unusable_component_cannot_be_evaluated_and_is_not_ended(status: str) -> None:
    m = _marker(_alert(), _inst(None, status=status))
    assert m.kind == "cannot_be_evaluated"


def test_asset_missing_from_a_working_tool_cannot_be_evaluated() -> None:
    other = {INST: {"status": "ok", "data": {"assets": []}}}
    assert _marker(_alert(), other).kind == "cannot_be_evaluated"


@pytest.mark.parametrize("status", ["resolved", "expired"])
def test_terminal_alerts_are_closed_regardless_of_the_snapshot(status: str) -> None:
    for results in (_inst("weak"), _inst("strong"), None):
        m = _marker(_alert(status=status), results)
        assert m.kind == "closed"
        assert m.evaluated_snapshot_id is None


def test_acknowledged_is_still_open_and_evaluated() -> None:
    assert _marker(_alert(status="acknowledged"), _inst("strong")).kind == "still_holds"


def test_no_snapshot_is_not_evaluated() -> None:
    assert _marker(_alert(), None).kind == "not_evaluated"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"tool_results": "nope"},
        {"tool_results": {}, "as_of": "not-a-date", "knowledge_time": "x"},
    ],
)
def test_unreadable_snapshot_never_raises(payload: Any) -> None:
    assert build_current_evaluation(1, payload) is None
    assert derive_marker(_alert(), build_current_evaluation(1, payload)).kind == "not_evaluated"


def test_investment_alerts_are_not_evaluated_here() -> None:
    inv = _alert(alert_type="investment_decision", dedup_key="investment:BTC")
    m = _marker(inv, _inst("strong"))
    assert m.kind == "not_evaluated"
    assert "investment_decision" in m.reason


def test_marker_does_not_mutate_the_alert_row() -> None:
    alert = _alert()
    before = dict(alert)
    _marker(alert, _inst("weak"))
    assert alert == before


def _row(**over: Any) -> dict[str, Any]:
    import uuid
    from datetime import UTC, datetime

    now = datetime(2026, 10, 19, tzinfo=UTC)
    row = _alert()
    row.update(
        uuid=uuid.uuid4(),
        severity="notable",
        domain="BTC",
        trigger_condition="x",
        reference_value=None,
        evidence_field_ids=[],
        snapshot_id=1,
        component_status="ok",
        data_quality_state="ok",
        acknowledged_at=None,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )
    row.update(over)
    return row


def test_api_response_carries_the_marker_and_leaves_status_untouched() -> None:
    from cfi.api.routes.alerts import _to_status

    current = build_current_evaluation(7, _payload(_inst("weak")))
    out = _to_status(_row(), current)
    assert out.status == "active"  # the marker never changes the stored status
    assert out.lifecycle_marker is not None
    assert out.lifecycle_marker.kind == "state_ended"
    assert out.lifecycle_marker.evaluated_snapshot_id == 7
    # A status-change response carries no evaluation: an open alert reads not_evaluated.
    bare = _to_status(_row())
    assert bare.lifecycle_marker is not None
    assert bare.lifecycle_marker.kind == "not_evaluated"
    assert _to_status(_row(status="resolved")).lifecycle_marker.kind == "closed"  # type: ignore[union-attr]

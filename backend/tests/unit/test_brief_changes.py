"""`compute_changes` (Phase 22 spec, Section 5): no previous brief means no defined comparison
basis at all (`comparison_basis="none"`, no changes); a previous snapshot payload yields exactly
the fields whose `display` text differs (changed and newly-appeared), never an unchanged field."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cfi.analyst.snapshot import Snapshot, SnapshotField
from cfi.brief.changes import compute_changes

AS_OF = datetime(2026, 9, 29, tzinfo=UTC)


def _snapshot(fields: list[SnapshotField]) -> Snapshot:
    return Snapshot(
        snapshot_id="deadbeef",
        snapshot_version="analyst_snapshot.v1",
        created_at=AS_OF,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question=None,
        tools_called=[],
        fields=fields,
        field_index={f.field_id: f for f in fields},
        raw={},
        data_quality_state="ok",
        has_conflicts=False,
    )


def test_no_previous_payload_means_no_defined_comparison_basis() -> None:
    current = _snapshot([SnapshotField("get_macro.dxy", "104.2", None)])
    changes = compute_changes(current, None)
    assert changes.comparison_basis == "none"
    assert changes.changes == []
    assert not changes.is_valid_change_id("chg.get_macro.dxy")


def test_unchanged_field_produces_no_change() -> None:
    current = _snapshot([SnapshotField("get_macro.dxy", "104.2", None)])
    previous_payload = {"fields": {"get_macro.dxy": {"display": "104.2"}}}
    changes = compute_changes(current, previous_payload)
    assert changes.comparison_basis == "previous_brief"
    assert changes.changes == []


def test_changed_field_is_reported_with_a_stable_change_id_and_numeric_delta() -> None:
    current = _snapshot([SnapshotField("get_macro.dxy", "106.0", None)])
    previous_payload = {"fields": {"get_macro.dxy": {"display": "104.0"}}}
    changes = compute_changes(current, previous_payload)
    assert len(changes.changes) == 1
    change = changes.changes[0]
    assert change.change_id == "chg.get_macro.dxy"
    assert change.previous_display == "104.0"
    assert change.current_display == "106.0"
    assert change.delta == "2.0"
    assert changes.is_valid_change_id("chg.get_macro.dxy")


def test_a_newly_populated_field_is_reported_with_no_previous_display() -> None:
    current = _snapshot([SnapshotField("get_anomalies.new_signal", "3.2", None)])
    previous_payload: dict[str, Any] = {"fields": {}}
    changes = compute_changes(current, previous_payload)
    assert len(changes.changes) == 1
    assert changes.changes[0].previous_display is None
    assert changes.changes[0].current_display == "3.2"


def test_non_numeric_display_change_has_no_delta_but_is_still_a_change() -> None:
    current = _snapshot([SnapshotField("get_market_regime.label", "leveraged_expansion", None)])
    previous_payload = {"fields": {"get_market_regime.label": {"display": "accumulation"}}}
    changes = compute_changes(current, previous_payload)
    assert len(changes.changes) == 1
    assert changes.changes[0].delta is None

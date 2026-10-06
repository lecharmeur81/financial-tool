"""Phase 41: pairing persisted assessments into history entries (pure, no database).

Pins the ordering and compatibility rules the user approved: newest first by ``snapshot_id`` only;
a predecessor under a different methodology or parameter version is ``Not Comparable (version
change)``, never silently compared; ``template_version`` alone never blocks a comparison;
``snapshot_as_of`` is reported as stored and flagged (``out_of_order_as_of``), never used to
reorder."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from cfi.decision_history import (
    ChangeKind,
    HistoryState,
    PersistedAssessment,
    build_history,
    compare_assessments,
)
from tests.decision_history_builders import BASE_TIME, persisted

BULLISH = ["S1", "S1", "S1", "S1", "S1"]
THIN = ["S1", "S1", "S1", "U", "U"]


def _newest_first(*rows: PersistedAssessment) -> list[PersistedAssessment]:
    return sorted(rows, key=lambda r: r.snapshot_id, reverse=True)


def test_a_single_assessment_has_an_explicit_no_previous_state() -> None:
    [entry] = build_history([persisted(BULLISH, snapshot_id=5)], limit=10)
    assert entry.state is HistoryState.NO_PREVIOUS
    assert entry.state.value == "No Previous Assessment"
    assert entry.change is None
    assert entry.previous_snapshot_id is None
    assert entry.out_of_order_as_of is False
    assert entry.to_dict()["change"] is None


def test_each_entry_is_compared_with_the_row_immediately_before_it() -> None:
    rows = _newest_first(
        persisted(BULLISH, snapshot_id=1),
        persisted(THIN, snapshot_id=2),
        persisted(BULLISH, snapshot_id=3),
    )
    entries = build_history(rows, limit=10)
    assert [e.assessment.snapshot_id for e in entries] == [3, 2, 1]
    assert [e.previous_snapshot_id for e in entries] == [2, 1, None]
    assert [e.state for e in entries] == [
        HistoryState.COMPARED,
        HistoryState.COMPARED,
        HistoryState.NO_PREVIOUS,
    ]
    by_id = {r.snapshot_id: r for r in rows}
    assert entries[0].change == compare_assessments(by_id[2], by_id[3])
    assert entries[1].change == compare_assessments(by_id[1], by_id[2])


def test_the_limit_returns_the_newest_entries_but_keeps_the_extra_predecessor() -> None:
    rows = _newest_first(*(persisted(BULLISH, snapshot_id=i) for i in (1, 2, 3, 4)))
    entries = build_history(rows, limit=2)
    assert [e.assessment.snapshot_id for e in entries] == [4, 3]
    assert entries[1].state is HistoryState.COMPARED  # compared with row 2, which is not returned
    assert entries[1].previous_snapshot_id == 2
    # with exactly `limit` rows the oldest one has nothing before it
    assert build_history(rows[:2], limit=2)[1].state is HistoryState.NO_PREVIOUS


def test_identical_consecutive_assessments_are_no_change() -> None:
    rows = _newest_first(persisted(BULLISH, snapshot_id=1), persisted(BULLISH, snapshot_id=2))
    [current, _] = build_history(rows, limit=2)
    assert current.change is not None
    assert current.change.kind is ChangeKind.NO_CHANGE


@pytest.mark.parametrize("field", ["methodology_version", "parameter_version"])
def test_a_version_change_is_not_comparable_and_never_silently_compared(field: str) -> None:
    edit: dict[str, Any] = {field: "older.v0"}
    old = replace(persisted(BULLISH, snapshot_id=1), **edit)
    new = persisted(THIN, snapshot_id=2)
    [entry, _] = build_history(_newest_first(old, new), limit=2)
    assert entry.state is HistoryState.NOT_COMPARABLE
    assert entry.state.value == "Not Comparable (version change)"
    assert entry.change is None
    assert entry.previous_snapshot_id == 1
    out = entry.to_dict()
    assert (
        out[
            "previous_methodology_version"
            if field == "methodology_version"
            else "previous_parameter_version"
        ]
        == "older.v0"
    )


def test_a_template_version_difference_alone_does_not_block_a_comparison() -> None:
    old = replace(persisted(BULLISH, snapshot_id=1), template_version="decision_templates.v-old")
    [entry, _] = build_history(_newest_first(old, persisted(BULLISH, snapshot_id=2)), limit=2)
    assert entry.state is HistoryState.COMPARED


def test_only_the_adjacent_row_decides_comparability() -> None:
    """Rows 1 (old version) -> 2 (new) -> 3 (new): 3 is compared with 2; 2 is not comparable."""
    rows = _newest_first(
        replace(persisted(BULLISH, snapshot_id=1), parameter_version="older.v0"),
        persisted(BULLISH, snapshot_id=2),
        persisted(THIN, snapshot_id=3),
    )
    states = [e.state for e in build_history(rows, limit=10)]
    assert states == [HistoryState.COMPARED, HistoryState.NOT_COMPARABLE, HistoryState.NO_PREVIOUS]


def test_ordering_is_by_snapshot_id_and_as_of_is_flagged_but_never_used_to_reorder() -> None:
    later_as_of = persisted(BULLISH, snapshot_id=1, as_of=BASE_TIME + timedelta(hours=5))
    back_dated = persisted(THIN, snapshot_id=2, as_of=BASE_TIME)  # recorded second, earlier as_of
    entries = build_history(_newest_first(later_as_of, back_dated), limit=2)
    current = entries[0]
    assert current.assessment.snapshot_id == 2  # the latest recorded, whatever its as_of
    assert current.out_of_order_as_of is True
    assert current.assessment.snapshot_as_of == BASE_TIME  # reported exactly as stored
    assert current.to_dict()["snapshot_as_of"] == BASE_TIME.isoformat()
    assert entries[1].out_of_order_as_of is False


def test_equal_or_later_as_of_is_not_out_of_order() -> None:
    same = build_history(
        _newest_first(
            persisted(BULLISH, snapshot_id=1, as_of=BASE_TIME),
            persisted(BULLISH, snapshot_id=2, as_of=BASE_TIME),
        ),
        limit=2,
    )
    assert same[0].out_of_order_as_of is False
    later = build_history(
        _newest_first(
            persisted(BULLISH, snapshot_id=1, as_of=BASE_TIME),
            persisted(BULLISH, snapshot_id=2, as_of=BASE_TIME + timedelta(minutes=1)),
        ),
        limit=2,
    )
    assert later[0].out_of_order_as_of is False


def test_out_of_order_is_flagged_even_when_the_pair_is_not_comparable() -> None:
    old = replace(
        persisted(BULLISH, snapshot_id=1, as_of=BASE_TIME + timedelta(hours=1)),
        methodology_version="older.v0",
    )
    [entry, _] = build_history(
        _newest_first(old, persisted(BULLISH, snapshot_id=2, as_of=BASE_TIME)), limit=2
    )
    assert entry.state is HistoryState.NOT_COMPARABLE
    assert entry.out_of_order_as_of is True


def test_mixed_scope_or_misordered_rows_are_refused() -> None:
    btc, eth = persisted(BULLISH, snapshot_id=2), persisted(BULLISH, snapshot_id=1, scope="ETH")
    with pytest.raises(ValueError, match="one scope"):
        build_history([btc, eth], limit=2)
    with pytest.raises(ValueError, match="newest-first"):
        build_history(
            [persisted(BULLISH, snapshot_id=1), persisted(BULLISH, snapshot_id=2)], limit=2
        )
    with pytest.raises(ValueError, match="limit"):
        build_history([btc], limit=0)


def test_an_empty_input_gives_no_entries() -> None:
    assert build_history([], limit=5) == ()


def test_entries_are_deterministic() -> None:
    rows = _newest_first(persisted(BULLISH, snapshot_id=1), persisted(THIN, snapshot_id=2))
    assert [e.to_dict() for e in build_history(rows, limit=2)] == [
        e.to_dict() for e in build_history(rows, limit=2)
    ]

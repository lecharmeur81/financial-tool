"""Phase 41: the pure comparison of two persisted decision assessments.

Assessments come from the real engine path (``tests.decision_history_builders``). Where a single
dimension has to be isolated, a copy of one persisted assessment is edited in exactly that
dimension; the comparison reads only the persisted fields, so that isolates the rule under test."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from cfi.decision.universe import Confidence, Stance
from cfi.decision_history import (
    AssessmentChange,
    ChangeDirection,
    ChangeKind,
    MalformedAssessmentError,
    PersistedAssessment,
    compare_assessments,
)
from cfi.decision_history import compare as compare_module
from cfi.decision_history import history as history_module
from tests.decision_history_builders import persisted

BULLISH = ["S1", "S1", "S1", "S1", "S1"]
BACKEND = Path(__file__).resolve().parents[2]


def _body(base: PersistedAssessment) -> dict[str, Any]:
    """A deep copy of the persisted JSON; the engine result is ``body["assessment"]``."""
    return copy.deepcopy(dict(base.assessment))


def _with(base: PersistedAssessment, body: dict[str, Any], **columns: Any) -> PersistedAssessment:
    return replace(base, assessment=body, **columns)


def _edited(base: PersistedAssessment, **edit: Any) -> PersistedAssessment:
    """A copy whose engine result has the given keys replaced."""
    body = _body(base)
    body["assessment"].update(edit)
    return replace(base, assessment=body)


def _only(change: AssessmentChange, kind: ChangeKind) -> None:
    assert change.kind is kind
    assert change.changed_dimensions == (kind,)


# --------------------------------------------------------------------------- no change
def test_identical_assessments_are_no_change() -> None:
    a, b = persisted(BULLISH, snapshot_id=1), persisted(BULLISH, snapshot_id=2)
    change = compare_assessments(a, b)
    assert change.kind is ChangeKind.NO_CHANGE
    assert change.changed_dimensions == ()
    assert change.stance.direction is ChangeDirection.UNCHANGED
    assert change.evidence.direction is ChangeDirection.UNCHANGED
    assert change.coverage.direction is ChangeDirection.UNCHANGED
    assert change.risk_direction is ChangeDirection.UNCHANGED
    assert change.evidence.items == ()


def test_the_decision_input_hash_is_reported_but_never_decides_the_classification() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    b = replace(persisted(BULLISH, snapshot_id=2), decision_input_hash="f" * 64)
    change = compare_assessments(a, b)
    assert change.same_decision_input is False
    assert change.kind is ChangeKind.NO_CHANGE  # the persisted assessments are what is compared


# --------------------------------------------------------------------------- single dimensions
def test_stance_change_only() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    change = compare_assessments(a, replace(a, snapshot_id=2, stance=Stance.STRONGLY_BULLISH.value))
    _only(change, ChangeKind.STANCE_CHANGED)
    assert change.stance.previous == "Bullish"
    assert change.stance.current == "Strongly Bullish"
    assert change.stance.direction is ChangeDirection.STRENGTHENED


def test_confidence_change_only() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    change = compare_assessments(a, replace(a, snapshot_id=2, confidence=Confidence.LOW.value))
    _only(change, ChangeKind.CONFIDENCE_CHANGED)
    assert change.confidence.direction is ChangeDirection.WEAKENED


def test_posture_change_only() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    change = compare_assessments(a, replace(a, snapshot_id=2, posture="WAIT FOR CONFIRMATION"))
    _only(change, ChangeKind.POSTURE_CHANGED)
    assert change.posture.direction is ChangeDirection.CHANGED
    assert change.posture.previous == "MONITOR CONSTRUCTIVE CONDITIONS"


def test_evidence_removed() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    dropped = body["assessment"]["supportive"].pop()
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.EVIDENCE_CHANGED)
    [item] = change.evidence.items
    assert (item.side, item.domain, item.change) == ("supportive", dropped["domain"], "removed")
    assert item.current is None
    assert item.previous is not None


def test_evidence_added() -> None:
    full, fewer = persisted(BULLISH, snapshot_id=2), persisted(BULLISH, snapshot_id=1)
    body = _body(fewer)
    dropped = body["assessment"]["supportive"].pop(0)
    change = compare_assessments(replace(fewer, assessment=body), full)
    _only(change, ChangeKind.EVIDENCE_CHANGED)
    [item] = change.evidence.items
    assert (item.side, item.domain, item.change) == ("supportive", dropped["domain"], "added")


def test_adverse_evidence_added_is_reported_on_the_adverse_side() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    body["assessment"]["adverse"].append(
        {**body["assessment"]["supportive"][0], "direction": "A", "domain": "macro"}
    )
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.EVIDENCE_CHANGED)
    [item] = change.evidence.items
    assert (item.side, item.domain, item.change) == ("adverse", "macro", "added")


def test_evidence_changed_in_place_reports_the_fields_and_strength_direction() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    body["assessment"]["supportive"][0]["strength"] = (
        "Strong" if a.assessment["assessment"]["supportive"][0]["strength"] != "Strong" else "Weak"
    )
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.EVIDENCE_CHANGED)
    [item] = change.evidence.items
    assert item.change == "changed"
    assert item.fields_changed == ("strength",)
    expected = (
        ChangeDirection.STRENGTHENED
        if body["assessment"]["supportive"][0]["strength"] == "Strong"
        else ChangeDirection.WEAKENED
    )
    assert item.strength_direction is expected


def test_a_conflict_flag_change_is_an_evidence_change() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    change = compare_assessments(a, replace(a, snapshot_id=2, conflict=True))
    _only(change, ChangeKind.EVIDENCE_CHANGED)
    assert change.evidence.conflict_previous is False
    assert change.evidence.conflict_current is True


def test_coverage_count_change_only() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    change = compare_assessments(a, replace(a, snapshot_id=2, coverage_available=4))
    _only(change, ChangeKind.COVERAGE_CHANGED)
    assert change.coverage.direction is ChangeDirection.DETERIORATED
    better = compare_assessments(replace(a, coverage_available=3), a)
    assert better.coverage.direction is ChangeDirection.IMPROVED


def test_a_limitation_change_is_a_coverage_and_data_quality_change() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    assert a.assessment["assessment"]["limitations"] == ["LIMIT.derivatives_freshness"]
    change = compare_assessments(a, _edited(replace(a, snapshot_id=2), limitations=[]))
    _only(change, ChangeKind.COVERAGE_CHANGED)
    assert change.coverage.limitations_removed == ("LIMIT.derivatives_freshness",)
    added = compare_assessments(_edited(a, limitations=[]), a)
    assert added.coverage.limitations_added == ("LIMIT.derivatives_freshness",)
    assert change.coverage.direction is ChangeDirection.CHANGED


def test_a_component_freshness_change_is_reported_without_a_availability_move() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    body["assessment"]["readings"][0]["freshness"] = "stale"
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.COVERAGE_CHANGED)
    [comp] = change.coverage.components
    assert comp.transition == "state_changed"
    assert change.coverage.direction is ChangeDirection.CHANGED


def test_risk_level_change_only() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    body["assessment"]["risks"][0]["level"] = "Elevated"
    body["assessment"]["max_risk"] = "Elevated"
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.RISK_CHANGED)
    assert change.risk_direction is ChangeDirection.DETERIORATED
    assert change.risk_max.direction is ChangeDirection.DETERIORATED
    [row] = change.risk_dimensions
    assert (row.previous, row.current) == ("Low", "Elevated")
    back = compare_assessments(replace(a, assessment=body), a)
    assert back.risk_direction is ChangeDirection.IMPROVED


def test_a_move_to_not_assessed_is_a_change_but_not_an_ordered_direction() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    body["assessment"]["risks"][1]["level"] = "Not assessed"
    change = compare_assessments(a, replace(a, snapshot_id=2, assessment=body))
    _only(change, ChangeKind.RISK_CHANGED)
    assert change.risk_direction is ChangeDirection.CHANGED


# --------------------------------------------------------------------------- real engine pairs
def test_a_real_reversal_changes_several_dimensions() -> None:
    change = compare_assessments(
        persisted(["S2"] * 5, snapshot_id=1), persisted(["A2"] * 5, snapshot_id=2)
    )
    assert change.kind is ChangeKind.MULTIPLE_CHANGES
    assert set(change.changed_dimensions) >= {
        ChangeKind.STANCE_CHANGED,
        ChangeKind.POSTURE_CHANGED,
        ChangeKind.EVIDENCE_CHANGED,
        ChangeKind.RISK_CHANGED,
    }
    assert change.stance.previous == "Strongly Bullish"
    assert change.stance.current == "Strongly Bearish"
    assert change.stance.direction is ChangeDirection.CHANGED  # opposite families
    assert change.risk_direction is ChangeDirection.DETERIORATED


def test_dimensions_are_listed_in_the_fixed_order() -> None:
    change = compare_assessments(
        persisted(["S2"] * 5, snapshot_id=1), persisted(["A2"] * 5, snapshot_id=2)
    )
    order = [
        ChangeKind.STANCE_CHANGED,
        ChangeKind.CONFIDENCE_CHANGED,
        ChangeKind.POSTURE_CHANGED,
        ChangeKind.EVIDENCE_CHANGED,
        ChangeKind.COVERAGE_CHANGED,
        ChangeKind.RISK_CHANGED,
    ]
    assert list(change.changed_dimensions) == [k for k in order if k in change.changed_dimensions]


def test_domains_becoming_unavailable_lower_coverage_and_are_named() -> None:
    change = compare_assessments(
        persisted(BULLISH, snapshot_id=1), persisted(["S1", "S1", "S1", "U", "U"], snapshot_id=2)
    )
    assert change.coverage.changed
    assert change.coverage.direction is ChangeDirection.DETERIORATED
    assert (change.coverage.previous_available, change.coverage.current_available) == (5, 3)
    assert change.coverage.directional_became_unavailable == ("macro", "market_structure")
    assert change.coverage.directional_became_available == ()
    assert {c.transition for c in change.coverage.components} >= {"became_unavailable"}
    assert change.confidence.direction is ChangeDirection.WEAKENED


def test_domains_becoming_available_raise_coverage_and_are_named() -> None:
    change = compare_assessments(
        persisted(["U", "S1", "S1", "S1", "S1"], snapshot_id=1), persisted(BULLISH, snapshot_id=2)
    )
    assert change.coverage.direction is ChangeDirection.IMPROVED
    assert change.coverage.directional_became_available == ("institutional",)
    [comp] = [c for c in change.coverage.components if c.component == "institutional.score"]
    assert comp.transition == "became_available"


def test_a_context_source_becoming_available_is_reported_separately() -> None:
    change = compare_assessments(
        persisted(BULLISH, snapshot_id=1, regime=None), persisted(BULLISH, snapshot_id=2)
    )
    assert change.coverage.context_became_available == ("regime",)
    assert change.coverage.directional_became_available == ()
    assert ChangeKind.COVERAGE_CHANGED in change.changed_dimensions


# --------------------------------------------------------------------------- directions
@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ("Bullish", "Bullish", ChangeDirection.UNCHANGED),
        ("Bullish", "Strongly Bullish", ChangeDirection.STRENGTHENED),
        ("Strongly Bullish", "Cautiously Bullish", ChangeDirection.WEAKENED),
        ("Bullish", "Neutral / Wait", ChangeDirection.WEAKENED),
        ("Neutral / Wait", "Cautiously Bearish", ChangeDirection.STRENGTHENED),
        ("Strongly Bearish", "Bearish", ChangeDirection.WEAKENED),
        ("Cautiously Bullish", "Cautiously Bearish", ChangeDirection.CHANGED),
        ("Bullish", "Strongly Bearish", ChangeDirection.CHANGED),
        ("Bullish", "Insufficient Evidence", ChangeDirection.INSUFFICIENT_EVIDENCE),
        ("Insufficient Evidence", "Bearish", ChangeDirection.INSUFFICIENT_EVIDENCE),
    ],
)
def test_stance_direction_follows_conviction_magnitude_within_a_family(
    previous: str, current: str, expected: ChangeDirection
) -> None:
    a = replace(persisted(BULLISH, snapshot_id=1), stance=previous)
    assert (
        compare_assessments(a, replace(a, snapshot_id=2, stance=current)).stance.direction
        is expected
    )


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ("Low", "Low", ChangeDirection.UNCHANGED),
        ("Low", "Moderate", ChangeDirection.STRENGTHENED),
        ("High", "Moderate", ChangeDirection.WEAKENED),
        ("High", "Insufficient Evidence", ChangeDirection.INSUFFICIENT_EVIDENCE),
        ("Insufficient Evidence", "Low", ChangeDirection.INSUFFICIENT_EVIDENCE),
    ],
)
def test_confidence_direction(previous: str, current: str, expected: ChangeDirection) -> None:
    a = replace(persisted(BULLISH, snapshot_id=1), confidence=previous)
    result = compare_assessments(a, replace(a, snapshot_id=2, confidence=current))
    assert result.confidence.direction is expected


# --------------------------------------------------------------------------- determinism
def test_the_same_inputs_always_give_the_same_result_and_inputs_are_not_mutated() -> None:
    a, b = (
        persisted(["S2"] * 5, snapshot_id=1),
        persisted(["S1", "S1", "U", "U", "A1"], snapshot_id=2),
    )
    before = (_body(a), _body(b))
    first, second = compare_assessments(a, b), compare_assessments(a, b)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert (dict(a.assessment), dict(b.assessment)) == before


def test_the_comparison_is_directional_not_symmetric() -> None:
    a, b = persisted(BULLISH, snapshot_id=1), persisted(["S1", "S1", "S1", "U", "U"], snapshot_id=2)
    assert compare_assessments(a, b).coverage.direction is ChangeDirection.DETERIORATED
    assert compare_assessments(b, a).coverage.direction is ChangeDirection.IMPROVED


def test_to_dict_is_json_plain() -> None:
    import json

    change = compare_assessments(
        persisted(["S2"] * 5, snapshot_id=1), persisted(["A2"] * 5, snapshot_id=2)
    )
    assert json.loads(json.dumps(change.to_dict())) == change.to_dict()


# --------------------------------------------------------------------------- contract guards
def test_a_persisted_assessment_missing_a_contract_field_is_refused_not_guessed() -> None:
    a = persisted(BULLISH, snapshot_id=1)
    body = _body(a)
    del body["assessment"]["risks"]
    with pytest.raises(MalformedAssessmentError):
        compare_assessments(a, replace(a, snapshot_id=2, assessment=body))


def test_the_classification_vocabulary_is_the_documented_one() -> None:
    assert {k.value for k in ChangeKind} == {
        "NO_CHANGE",
        "STANCE_CHANGED",
        "CONFIDENCE_CHANGED",
        "POSTURE_CHANGED",
        "EVIDENCE_CHANGED",
        "COVERAGE_CHANGED",
        "RISK_CHANGED",
        "MULTIPLE_CHANGES",
    }
    assert {d.value for d in ChangeDirection} == {
        "improved",
        "deteriorated",
        "strengthened",
        "weakened",
        "changed",
        "unchanged",
        "insufficient evidence",
    }


@pytest.mark.parametrize("module", [compare_module, history_module])
def test_the_comparison_modules_are_pure(module: Any) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    forbidden = {
        "sqlalchemy",
        "psycopg",
        "redis",
        "httpx",
        "requests",
        "anthropic",
        "random",
        "time",
    }
    assert not (imported & forbidden)
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "datetime.now" not in text
    assert "utcnow" not in text
    # it never reaches into the engine: only the closed vocabularies are imported
    assert "cfi.decision.engine" not in text
    assert "cfi.decision.rules" not in text


def test_no_decision_logic_is_duplicated_here() -> None:
    text = (BACKEND / "src/cfi/decision_history/compare.py").read_text(encoding="utf-8")
    assert "assess(" not in text
    assert "build_decision_context" not in text

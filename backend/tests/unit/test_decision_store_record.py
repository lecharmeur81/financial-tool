"""Phase 40: the pure part of decision-assessment persistence (no database).

A stored snapshot is turned into assessment rows by the existing Phase 38.3
``build_decision_context`` - the same engine path the Phase 39 read service uses - so these tests
pin: same engine and inputs give the same stored assessment, identity excludes ``template_version``,
a producer-hash mismatch is recorded (not hidden, not repaired), and ``Insufficient Evidence`` is a
valid, persistable result. Also pinned: the migration's closed vocabularies equal the engine enums.
"""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cfi.decision import universe
from cfi.decision.context import InvalidSnapshotError, build_decision_context
from cfi.decision.identity import HashCheck, producer_payload_hash
from cfi.decision.universe import (
    METHODOLOGY_VERSION,
    PARAMETER_VERSION,
    SCOPE_DOMAINS,
    TEMPLATE_VERSION,
    Confidence,
    Posture,
    Stance,
)
from cfi.decision_store import record as record_module
from cfi.decision_store.record import StoredSnapshot, record_from_context, records_for_snapshot
from tests.decision_builders import make_payload
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
BACKEND = Path(__file__).resolve().parents[2]


def _stored(
    payload: dict[str, Any], *, row_id: int = 7, payload_hash: str | None = None
) -> StoredSnapshot:
    payload = stored_form(payload)
    return StoredSnapshot(
        row_id=row_id,
        uuid="11111111-1111-4111-8111-111111111111",
        payload_hash=payload_hash or producer_payload_hash(payload),
        created_at=NOW,
        as_of=NOW,
        knowledge_time=NOW,
        payload=payload,
    )


def test_one_record_per_defined_scope_in_engine_order() -> None:
    records = records_for_snapshot(_stored(live_state_payload()))
    assert [r.scope for r in records] == list(SCOPE_DOMAINS)
    assert [r.scope for r in records] == ["BTC", "ETH", "SOL", "XRP"]


def test_records_carry_the_snapshot_identity_and_every_version() -> None:
    snap = _stored(live_state_payload(), row_id=42)
    for r in records_for_snapshot(snap):
        assert r.snapshot_id == 42
        assert r.methodology_version == METHODOLOGY_VERSION == "decision_methodology.v0"
        assert r.parameter_version == PARAMETER_VERSION == "decision_params.v0"
        assert r.template_version == TEMPLATE_VERSION == "decision_templates.v0"
        assert r.snapshot_version == "analyst_snapshot.v1"
        assert r.snapshot_as_of == NOW
        assert r.knowledge_time == NOW
        assert r.producer_payload_hash == snap.payload_hash
        assert r.producer_hash_check == HashCheck.VERIFIED.value
        assert len(r.decision_input_hash) == 64


def test_the_stored_assessment_is_exactly_the_engines_deterministic_output() -> None:
    """The persisted JSON is what the Phase 39 path computes from the same stored row - no
    separate decision logic exists in the persistence layer."""
    snap = _stored(live_state_payload())
    for r in records_for_snapshot(snap):
        live = build_decision_context(snap.payload, r.scope, snapshot_ref=snap.ref())
        assert r.assessment == live.deterministic_dict()
        assert "generated_at" not in r.assessment
        assert r.stance == live.final_stance.value
        assert r.confidence == live.confidence.value
        assert r.posture == live.posture.value
        assert r.conflict == live.conflict
        assert r.coverage_available == live.assessment.coverage_available
        assert r.expected_domains == live.assessment.expected_domains


def test_identity_is_deterministic_and_excludes_the_template_version() -> None:
    snap = _stored(live_state_payload(), row_id=9)
    first = records_for_snapshot(snap)
    second = records_for_snapshot(snap)
    assert first == second
    for r in first:
        assert r.identity == (9, r.scope, METHODOLOGY_VERSION, PARAMETER_VERSION)
        assert TEMPLATE_VERSION not in r.identity
    # a different template version is the same assessment identity: the first (immutable) row
    # stands, and the new version is provenance only
    bumped = replace(first[0], template_version="decision_templates.v9")
    assert bumped.identity == first[0].identity


def test_insufficient_evidence_is_a_valid_persistable_assessment() -> None:
    records = records_for_snapshot(_stored(live_state_payload()))
    btc = next(r for r in records if r.scope == "BTC")
    assert btc.stance == Stance.INSUFFICIENT.value
    assert btc.confidence == Confidence.INSUFFICIENT.value
    assert btc.posture == Posture.INVESTIGATE_FURTHER.value
    assert btc.coverage_available < btc.expected_domains  # missing evidence stays visible
    assert btc.assessment["summary"]["missing"]  # and is listed, never turned into a neutral value


def test_a_producer_hash_mismatch_is_recorded_not_discarded() -> None:
    snap = _stored(live_state_payload(), payload_hash="0" * 64)
    records = records_for_snapshot(snap)
    assert len(records) == 4
    for r in records:
        assert r.producer_hash_check == HashCheck.MISMATCH.value
        assert r.producer_payload_hash == "0" * 64  # as stored, never repaired
        # the mismatch changes no decision: same stance as the verified snapshot
    verified = records_for_snapshot(_stored(live_state_payload()))
    assert [r.stance for r in records] == [r.stance for r in verified]
    assert [r.decision_input_hash for r in records] == [r.decision_input_hash for r in verified]


def test_a_payload_that_is_not_a_supported_snapshot_raises() -> None:
    snap = StoredSnapshot(1, "u", "h", NOW, NOW, NOW, {"snapshot_version": "other.v9"})
    with pytest.raises(InvalidSnapshotError):
        records_for_snapshot(snap)


def test_record_from_context_matches_records_for_snapshot() -> None:
    snap = _stored(live_state_payload())
    ctx = build_decision_context(snap.payload, "ETH", snapshot_ref=snap.ref())
    assert record_from_context(ctx, snap) == next(
        r for r in records_for_snapshot(snap) if r.scope == "ETH"
    )


def _migration() -> Any:
    path = next((BACKEND / "migrations" / "versions").glob("*_0013_decision_assessment.py"))
    spec = importlib.util.spec_from_file_location("migration_0013", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_check_vocabularies_equal_the_engine_enums() -> None:
    m = _migration()
    assert m.revision == "0013"
    assert m.down_revision == "0012"
    assert set(m.STANCES) == {s.value for s in Stance}
    assert set(m.CONFIDENCES) == {c.value for c in Confidence}
    assert set(m.POSTURES) == {p.value for p in Posture}
    assert set(m.SCOPES) == set(SCOPE_DOMAINS)
    assert set(m.HASH_CHECKS) == {h.value for h in HashCheck}


def test_the_record_module_stays_database_free() -> None:
    tree = ast.parse(Path(record_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"sqlalchemy", "psycopg", "redis", "celery", "httpx", "anthropic"}


def test_universe_scopes_are_the_four_assets() -> None:
    assert tuple(universe.SCOPE_DOMAINS) == ("BTC", "ETH", "SOL", "XRP")


def test_insert_snapshot_is_the_only_writer_of_ai_snapshot() -> None:
    """Every producer must go through ``AnalystRepository.insert_snapshot`` (which persists the
    assessments). A second writer of ``ai.snapshot`` would silently bypass Phase 40 persistence."""
    src = Path(record_module.__file__).resolve().parents[1]
    writers = [
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if "insert(t.ai_snapshot)" in path.read_text(encoding="utf-8")
    ]
    assert writers == ["analyst/repository.py"]


@pytest.mark.parametrize(
    ("context", "expected_final", "expected_posture"),
    [
        ({}, "Strongly Bullish", "MONITOR CONSTRUCTIVE CONDITIONS"),
        ({"regime": None}, "Neutral / Wait", "WAIT FOR CONFIRMATION"),
        (
            {"derivatives": None, "volatility": None},
            "Cautiously Bullish",
            "AVOID ADDING HIGH-RISK EXPOSURE",
        ),
    ],
)
def test_the_final_stance_not_the_raw_one_is_stored_with_the_engines_own_posture(
    context: dict[str, Any], expected_final: str, expected_posture: str
) -> None:
    """A strongly bullish directional picture is limited when a cap source is missing (CAP-U). The
    row carries the engine's *final* stance and posture; the raw stance stays inside the JSON."""
    payload = make_payload(["S2", "S1", "N", "S1", "S2"], **context)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    btc = next(r for r in records_for_snapshot(_stored(payload)) if r.scope == "BTC")
    assert btc.stance == expected_final
    assert btc.posture == expected_posture
    assert btc.assessment["summary"]["raw_stance"] == "Strongly Bullish"
    assert btc.assessment["summary"]["final_stance"] == expected_final

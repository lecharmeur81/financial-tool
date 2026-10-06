"""Builders for Phase 41 history tests: persisted assessments produced by the REAL engine path
(``cfi.decision_store.record.records_for_snapshot``), so history tests compare the same JSON shape
Phase 40 persists - never a hand-written imitation of it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from cfi.decision.identity import producer_payload_hash
from cfi.decision_history import PersistedAssessment
from cfi.decision_store.record import AssessmentRecord, StoredSnapshot, records_for_snapshot
from tests.decision_builders import make_payload
from tests.decision_snapshots import stored_form

BASE_TIME = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def stored_snapshot(
    codes: Sequence[str],
    *,
    snapshot_id: int,
    as_of: datetime | None = None,
    **context: Any,
) -> StoredSnapshot:
    payload = make_payload(codes, **context)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    when = as_of or BASE_TIME + timedelta(minutes=snapshot_id)
    payload["as_of"] = when.isoformat()
    payload["knowledge_time"] = when.isoformat()
    payload = stored_form(payload)
    return StoredSnapshot(
        row_id=snapshot_id,
        uuid="11111111-1111-4111-8111-111111111111",
        payload_hash=producer_payload_hash(payload),
        created_at=when,
        as_of=when,
        knowledge_time=when,
        payload=payload,
    )


def to_persisted(record: AssessmentRecord, *, created_at: datetime) -> PersistedAssessment:
    return PersistedAssessment(
        snapshot_id=record.snapshot_id,
        scope=record.scope,
        methodology_version=record.methodology_version,
        parameter_version=record.parameter_version,
        template_version=record.template_version,
        snapshot_as_of=record.snapshot_as_of,
        created_at=created_at,
        producer_hash_check=record.producer_hash_check,
        decision_input_hash=record.decision_input_hash,
        stance=record.stance,
        confidence=record.confidence,
        posture=record.posture,
        coverage_available=record.coverage_available,
        expected_domains=record.expected_domains,
        conflict=record.conflict,
        assessment=record.assessment,
    )


def persisted(
    codes: Sequence[str],
    *,
    snapshot_id: int = 1,
    as_of: datetime | None = None,
    scope: str = "BTC",
    **context: Any,
) -> PersistedAssessment:
    """The persisted assessment of ``scope`` for a snapshot built from ``codes``."""
    snap = stored_snapshot(codes, snapshot_id=snapshot_id, as_of=as_of, **context)
    record = next(r for r in records_for_snapshot(snap) if r.scope == scope)
    return to_persisted(record, created_at=snap.created_at)

"""Phase 40: decision-assessment persistence against a real PostgreSQL (the isolated test database).

Snapshots are stored through the platform's own ``AnalystRepository.insert_snapshot`` - the one
boundary every snapshot producer goes through - and the ``sig.decision_assessment`` rows that
result are compared with a fresh computation from the stored row. The ``db`` fixture empties the
test database first and refuses to run against any database whose name does not end in ``_test``;
nothing here touches Redis or the runtime database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.repository import AnalystRepository
from cfi.db import tables as t
from cfi.decision.context import build_decision_context
from cfi.decision.universe import METHODOLOGY_VERSION, PARAMETER_VERSION, TEMPLATE_VERSION
from cfi.decision_store import DecisionAssessmentRepository
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
A = t.decision_assessment


async def _store(
    db: AsyncEngine, payload: dict[str, Any] | None = None, *, payload_hash: str | None = None
) -> int:
    from cfi.decision.identity import producer_payload_hash

    stored = stored_form(payload if payload is not None else live_state_payload())
    row_id, _ = await AnalystRepository(db).insert_snapshot(
        created_at=NOW,
        as_of=NOW,
        knowledge_time=NOW,
        snapshot_version=str(stored.get("snapshot_version", "analyst_snapshot.v1")),
        payload=stored,
        payload_hash=payload_hash or producer_payload_hash(stored),
    )
    return row_id


async def _rows(db: AsyncEngine, snapshot_id: int | None = None) -> list[Any]:
    stmt = select(A).order_by(A.c.snapshot_id, A.c.scope)
    if snapshot_id is not None:
        stmt = stmt.where(A.c.snapshot_id == snapshot_id)
    async with db.connect() as conn:
        return list((await conn.execute(stmt)).all())


async def test_every_stored_snapshot_gets_one_assessment_per_scope(db: AsyncEngine) -> None:
    snapshot_id = await _store(db)
    rows = await _rows(db, snapshot_id)
    assert [r.scope for r in rows] == ["BTC", "ETH", "SOL", "XRP"]
    for r in rows:
        assert r.snapshot_id == snapshot_id
        assert r.methodology_version == METHODOLOGY_VERSION
        assert r.parameter_version == PARAMETER_VERSION
        assert r.template_version == TEMPLATE_VERSION
        assert r.snapshot_version == "analyst_snapshot.v1"
        assert r.snapshot_as_of == NOW
        assert r.knowledge_time == NOW
        assert r.created_at == NOW  # the snapshot's own time: no wall clock inside persistence
        assert r.producer_hash_check == "verified"
        assert len(r.decision_input_hash) == 64


async def test_the_persisted_assessment_equals_a_fresh_computation_from_the_stored_row(
    db: AsyncEngine,
) -> None:
    snapshot_id = await _store(db)
    stored = await DecisionAssessmentRepository(db).get_snapshot(snapshot_id)
    assert stored is not None
    for r in await _rows(db, snapshot_id):
        live = build_decision_context(stored.payload, r.scope, snapshot_ref=stored.ref())
        expected = json.loads(json.dumps(live.deterministic_dict(), default=str))
        assert r.assessment == expected
        assert r.stance == live.final_stance.value
        assert r.decision_input_hash == live.identity.decision_input_hash


async def test_insufficient_evidence_is_persisted_as_a_normal_assessment(db: AsyncEngine) -> None:
    snapshot_id = await _store(db)  # the live data state: four domains have no data
    btc = next(r for r in await _rows(db, snapshot_id) if r.scope == "BTC")
    assert btc.stance == "Insufficient Evidence"
    assert btc.confidence == "Insufficient Evidence"
    assert btc.posture == "INVESTIGATE FURTHER"
    assert btc.coverage_available < btc.expected_domains
    assert btc.assessment["summary"]["missing"]


async def test_reprocessing_the_same_snapshot_creates_no_duplicates(db: AsyncEngine) -> None:
    snapshot_id = await _store(db)
    repo = DecisionAssessmentRepository(db)
    assert await repo.record_for_snapshot(snapshot_id, created_at=NOW) == 0
    assert await repo.record_for_snapshot(snapshot_id, created_at=NOW) == 0
    assert len(await _rows(db, snapshot_id)) == 4
    before = [(r.id, r.uuid) for r in await _rows(db, snapshot_id)]
    await repo.record_for_snapshot(snapshot_id, created_at=NOW)
    assert [(r.id, r.uuid) for r in await _rows(db, snapshot_id)] == before  # rows untouched


async def test_two_snapshots_are_assessed_independently(db: AsyncEngine) -> None:
    first = await _store(db)
    second = await _store(db)
    assert first != second
    assert len(await _rows(db, first)) == 4
    assert len(await _rows(db, second)) == 4
    async with db.connect() as conn:
        total = (await conn.execute(select(func.count()).select_from(A))).scalar_one()
    assert total == 8


async def test_the_database_itself_rejects_a_duplicate_identity(db: AsyncEngine) -> None:
    snapshot_id = await _store(db)
    row = dict((await _rows(db, snapshot_id))[0]._mapping)
    row.pop("id")
    row["uuid"] = uuid.uuid4()
    async with db.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(A.insert().values(**row))
        await conn.rollback()
    # a different parameter version is a different identity and is allowed
    row["uuid"] = uuid.uuid4()
    row["parameter_version"] = "decision_params.v1"
    async with db.begin() as conn:
        await conn.execute(A.insert().values(**row))
    assert len(await _rows(db, snapshot_id)) == 5


async def test_foreign_key_and_vocabulary_constraints(db: AsyncEngine) -> None:
    snapshot_id = await _store(db)
    base = dict((await _rows(db, snapshot_id))[0]._mapping)
    base.pop("id")

    async def attempt(**changes: Any) -> None:
        row = {**base, "uuid": uuid.uuid4(), "parameter_version": "decision_params.vX"}
        row.update(changes)
        async with db.connect() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(A.insert().values(**row))
            await conn.rollback()

    await attempt(snapshot_id=snapshot_id + 999)  # no such ai.snapshot row
    await attempt(stance="Very Bullish")
    await attempt(posture="BUY")
    await attempt(confidence="Certain")
    await attempt(scope="DOGE")
    await attempt(producer_hash_check="fine")


async def test_a_producer_hash_mismatch_is_persisted_and_recorded(db: AsyncEngine) -> None:
    snapshot_id = await _store(db, payload_hash="f" * 64)
    rows = await _rows(db, snapshot_id)
    assert len(rows) == 4
    for r in rows:
        assert r.producer_hash_check == "mismatch"
        assert r.producer_payload_hash == "f" * 64


async def test_a_payload_without_a_decision_still_creates_the_snapshot(db: AsyncEngine) -> None:
    async with db.connect() as conn:
        before = (await conn.execute(text("SELECT count(*) FROM ai.snapshot"))).scalar_one()
    snapshot_id = await _store(db, {"snapshot_version": "analyst_snapshot.v1", "tool_results": {}})
    async with db.connect() as conn:
        after = (await conn.execute(text("SELECT count(*) FROM ai.snapshot"))).scalar_one()
    assert after == before + 1
    assert snapshot_id > 0
    assert await _rows(db, snapshot_id) == []  # nothing assessable, nothing written, no error


async def test_a_persistence_failure_never_blocks_snapshot_creation(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(DecisionAssessmentRepository, "insert_many", boom)
    snapshot_id = await _store(db)  # must not raise
    assert snapshot_id > 0
    async with db.connect() as conn:
        found = (
            await conn.execute(select(t.ai_snapshot.c.id).where(t.ai_snapshot.c.id == snapshot_id))
        ).scalar_one()
    assert found == snapshot_id
    assert await _rows(db, snapshot_id) == []  # all or nothing: nothing was half-written


async def test_all_scopes_of_a_snapshot_are_written_in_one_transaction(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If any row of the batch is rejected, none of the snapshot's assessments is persisted."""
    from cfi.decision_store import record as record_module

    original = record_module.records_for_snapshot

    def corrupt(snapshot: Any) -> Any:
        records = list(original(snapshot))
        records[-1] = replace(records[-1], stance="Not A Stance")
        return tuple(records)

    monkeypatch.setattr("cfi.decision_store.repository.records_for_snapshot", corrupt)
    snapshot_id = await _store(db)  # persistence fails safely (CHECK violation on one row)
    assert await _rows(db, snapshot_id) == []

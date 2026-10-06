"""Decision-assessment persistence (``sig.decision_assessment``), Phase 40.

Same style as the other repositories (``cfi.realtime.repository``): SQLAlchemy Core, each write in
its own short transaction. All scopes of one snapshot are written in ONE transaction, so a snapshot
is either assessed completely or not at all, and every insert is
``ON CONFLICT (snapshot_id, scope, methodology_version, parameter_version) DO NOTHING``: the same
snapshot can be processed any number of times and still yields exactly one row per scope.
Rows are immutable; there is no update path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.core.logging import get_logger
from cfi.db import tables as t
from cfi.decision.context import InvalidSnapshotError
from cfi.decision_store.record import AssessmentRecord, StoredSnapshot, records_for_snapshot

log = get_logger(__name__)

IDENTITY_COLUMNS = ["snapshot_id", "scope", "methodology_version", "parameter_version"]


class DecisionAssessmentRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get_snapshot(self, snapshot_id: int) -> StoredSnapshot | None:
        """The stored row exactly as the Phase 39 read path sees it (after the JSONB round trip)."""
        s = t.ai_snapshot
        stmt = select(
            s.c.id, s.c.uuid, s.c.payload_hash, s.c.created_at, s.c.as_of, s.c.knowledge_time,
            s.c.payload,
        ).where(s.c.id == snapshot_id)  # fmt: skip
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        if row is None:
            return None
        return StoredSnapshot(
            row_id=int(row.id),
            uuid=str(row.uuid),
            payload_hash=str(row.payload_hash),
            created_at=row.created_at,
            as_of=row.as_of,
            knowledge_time=row.knowledge_time,
            payload=row.payload,
        )

    async def insert_many(
        self, records: tuple[AssessmentRecord, ...], *, created_at: datetime
    ) -> int:
        """Insert the records in one transaction; returns how many rows were actually new."""
        if not records:
            return 0
        rows = [
            {
                "uuid": uuid.uuid4(),
                "created_at": created_at,
                "snapshot_id": r.snapshot_id,
                "scope": r.scope,
                "methodology_version": r.methodology_version,
                "parameter_version": r.parameter_version,
                "template_version": r.template_version,
                "snapshot_version": r.snapshot_version,
                "snapshot_as_of": r.snapshot_as_of,
                "knowledge_time": r.knowledge_time,
                "producer_payload_hash": r.producer_payload_hash,
                "producer_hash_check": r.producer_hash_check,
                "decision_input_hash": r.decision_input_hash,
                "stance": r.stance,
                "confidence": r.confidence,
                "posture": r.posture,
                "coverage_available": r.coverage_available,
                "expected_domains": r.expected_domains,
                "conflict": r.conflict,
                "assessment": r.assessment,
            }
            for r in records
        ]
        stmt = (
            insert(t.decision_assessment)
            .values(rows)
            .on_conflict_do_nothing(index_elements=IDENTITY_COLUMNS)
            .returning(t.decision_assessment.c.id)
        )
        async with self.engine.begin() as conn:
            return len((await conn.execute(stmt)).all())

    async def record_for_snapshot(self, snapshot_id: int, *, created_at: datetime) -> int:
        """Assess a stored snapshot and persist the result; returns the number of new rows.

        Returns 0 (and writes nothing) for a payload that is not a supported snapshot - e.g. a
        synthetic test payload - since such a snapshot has no decision to record."""
        snapshot = await self.get_snapshot(snapshot_id)
        if snapshot is None:
            return 0
        try:
            records = records_for_snapshot(snapshot)
        except InvalidSnapshotError:
            log.debug("decision_assessment_skipped_unsupported_snapshot", snapshot_id=snapshot_id)
            return 0
        return await self.insert_many(records, created_at=created_at)


async def persist_assessments_safely(
    engine: AsyncEngine, snapshot_id: int, *, created_at: datetime
) -> int:
    """``record_for_snapshot`` that can never raise into the caller.

    Used at the shared snapshot-insert boundary: failing to assess a snapshot must never change,
    delay-fail or undo the creation of the snapshot itself. The failure is logged, not hidden."""
    try:
        return await DecisionAssessmentRepository(engine).record_for_snapshot(
            snapshot_id, created_at=created_at
        )
    except Exception:
        log.warning("decision_assessment_persist_failed", snapshot_id=snapshot_id, exc_info=True)
        return 0

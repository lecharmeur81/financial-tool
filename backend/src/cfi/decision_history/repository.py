"""Read-only access to persisted assessments for the history view (Phase 41).

One ``SELECT`` per request over ``sig.decision_assessment`` (Phase 40); never writes. Rows are
returned newest first by ``snapshot_id`` - the order the system recorded them, the same definition
of "current" as ``GET /api/v1/decision/current``. No new index or table: the unique identity index
starts with ``snapshot_id``, and every snapshot has one row per scope.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t
from cfi.decision_history.compare import PersistedAssessment

__all__ = ["DecisionHistoryRepository"]


class DecisionHistoryRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def recent_for_scope(self, scope: str, *, count: int) -> tuple[PersistedAssessment, ...]:
        """The newest ``count`` assessments of one scope, newest first by ``snapshot_id``."""
        a = t.decision_assessment
        stmt = (
            select(a)
            .where(a.c.scope == scope)
            .order_by(a.c.snapshot_id.desc(), a.c.id.desc())
            .limit(count)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return tuple(
            PersistedAssessment(
                snapshot_id=int(r.snapshot_id),
                scope=str(r.scope),
                methodology_version=str(r.methodology_version),
                parameter_version=str(r.parameter_version),
                template_version=str(r.template_version),
                snapshot_as_of=r.snapshot_as_of,
                created_at=r.created_at,
                producer_hash_check=str(r.producer_hash_check),
                decision_input_hash=str(r.decision_input_hash),
                stance=str(r.stance),
                confidence=str(r.confidence),
                posture=str(r.posture),
                coverage_available=int(r.coverage_available),
                expected_domains=int(r.expected_domains),
                conflict=bool(r.conflict),
                assessment=r.assessment,
            )
            for r in rows
        )

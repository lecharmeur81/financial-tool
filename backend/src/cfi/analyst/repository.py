"""AI Analyst persistence (``ai.snapshot`` / ``ai.interpretation`` / ``ai.usage``).

The first write path in this codebase outside ``cfi.ingestion`` (every engine from Phase 13 onward
is read-only, computed live at request time — ARCHITECTURE.md's layer rule, A2/R2). Follows
``cfi.ingestion.repository.IngestionRepository``'s own style exactly: raw SQLAlchemy Core
``insert``/``update`` per write, each in its own short transaction, never one shared ORM session, so
a failed write never corrupts a wider transaction (R13: reuse the established pattern, do not invent
a parallel one).

Every table exposes a stable, public ``uuid`` column (Section 13: "analysis ID") alongside its
internal ``bigint`` primary key (the codebase's own established convention — see ``db/tables.py``'s
``quality_check_result`` and every ``ops.*`` table); callers outside this module address rows by
``uuid``, never by the internal ``id``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t
from cfi.decision_store.repository import persist_assessments_safely


class SnapshotRow(NamedTuple):
    """One stored ``ai.snapshot`` row, as the read path needs it (Phase 39)."""

    row_id: int
    uuid: str
    payload_hash: str
    created_at: datetime
    payload: dict[str, Any]


class AnalystRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ snapshot (immutable)

    async def insert_snapshot(
        self,
        *,
        created_at: datetime,
        as_of: datetime,
        knowledge_time: datetime,
        snapshot_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> tuple[int, uuid.UUID]:
        """Insert one immutable evidence snapshot. Never updated after insert (ADR-0068).

        The snapshot's deterministic decision assessments are persisted right after (Phase 40),
        best-effort: see ``persist_assessments_safely``. The return value is unchanged."""
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.ai_snapshot)
            .values(
                uuid=row_uuid,
                created_at=created_at,
                as_of=as_of,
                knowledge_time=knowledge_time,
                snapshot_version=snapshot_version,
                payload=payload,
                payload_hash=payload_hash,
            )
            .returning(t.ai_snapshot.c.id)
        )
        async with self.engine.begin() as conn:
            snapshot_id = int((await conn.execute(stmt)).scalar_one())
        # Phase 40: the one boundary every snapshot producer (alerts cycle, analyst, brief,
        # journal, paper) goes through, so every stored snapshot gets its deterministic decision
        # assessment. Runs AFTER the snapshot's own transaction has committed, in its own
        # transaction, and can never raise: the snapshot is created exactly as before.
        await persist_assessments_safely(self.engine, snapshot_id, created_at=created_at)
        return snapshot_id, row_uuid

    async def latest_snapshot(self) -> tuple[int, dict[str, Any]] | None:
        """The most recently inserted ``ai.snapshot`` row, regardless of which feature created it
        (analyst, brief, or alerts) — read-only, additive (Phase 23 spec "Phase 21/22 Integration":
        "reuse the existing Phase 21 grounding/provenance mechanisms where applicable"). Used by
        ``cfi.alerts.service.AlertService`` as the prior-cycle comparison basis, the same way
        ``cfi.brief.repository.BriefRepository.get_snapshot_payload`` reads one specific snapshot
        by id for the brief's own comparison basis — this is the only new read ``ai.snapshot``
        needed, not a second snapshot table."""
        stmt = (
            select(t.ai_snapshot.c.id, t.ai_snapshot.c.payload)
            .order_by(t.ai_snapshot.c.created_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return (int(row[0]), row[1]) if row else None

    async def latest_snapshot_row(self) -> SnapshotRow | None:
        """The most recent ``ai.snapshot`` row with its identity columns (Phase 39).

        Read-only, and additive: ``latest_snapshot`` above is unchanged. It returns the same
        row, plus the ``uuid``, ``payload_hash`` and ``created_at`` the Decision Context needs to
        build a ``SnapshotRef`` - the decision read path reads a stored snapshot, it never builds
        one. ``id`` breaks a ``created_at`` tie deterministically."""
        stmt = (
            select(
                t.ai_snapshot.c.id,
                t.ai_snapshot.c.uuid,
                t.ai_snapshot.c.payload_hash,
                t.ai_snapshot.c.created_at,
                t.ai_snapshot.c.payload,
            )
            .order_by(t.ai_snapshot.c.created_at.desc(), t.ai_snapshot.c.id.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        if row is None:
            return None
        return SnapshotRow(
            row_id=int(row[0]),
            uuid=str(row[1]),
            payload_hash=str(row[2]),
            created_at=row[3],
            payload=row[4],
        )

    # ------------------------------------------------------------------ interpretation (job record)

    async def create_queued_interpretation(
        self, *, now: datetime, question: str | None
    ) -> tuple[int, uuid.UUID]:
        """Create the ``queued`` row *before* the worker task runs, so its ``uuid`` is a stable
        ``analysis_id`` the API can return immediately (Section 13)."""
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.ai_interpretation)
            .values(
                uuid=row_uuid,
                created_at=now,
                updated_at=now,
                snapshot_id=None,
                status="queued",
                question=question,
                prompt_version=None,
                model=None,
                response=None,
                validation_status=None,
                validation_errors=None,
                attempt_count=0,
                tools_called=None,
                data_quality_state=None,
                error=None,
            )
            .returning(t.ai_interpretation.c.id)
        )
        async with self.engine.begin() as conn:
            interpretation_id = int((await conn.execute(stmt)).scalar_one())
        return interpretation_id, row_uuid

    async def mark_running(self, interpretation_id: int, *, now: datetime) -> None:
        await self._update_interpretation(interpretation_id, status="running", updated_at=now)

    async def mark_completed(
        self,
        interpretation_id: int,
        *,
        now: datetime,
        snapshot_id: int,
        prompt_version: str,
        model: str,
        response: dict[str, Any],
        validation_status: str,
        validation_errors: list[str],
        attempt_count: int,
        tools_called: list[str],
        data_quality_state: str,
    ) -> None:
        await self._update_interpretation(
            interpretation_id,
            status="completed",
            updated_at=now,
            snapshot_id=snapshot_id,
            prompt_version=prompt_version,
            model=model,
            response=response,
            validation_status=validation_status,
            validation_errors=validation_errors,
            attempt_count=attempt_count,
            tools_called=tools_called,
            data_quality_state=data_quality_state,
        )

    async def mark_failed(
        self,
        interpretation_id: int,
        *,
        now: datetime,
        error: str,
        snapshot_id: int | None = None,
        prompt_version: str | None = None,
        model: str | None = None,
        validation_status: str | None = None,
        validation_errors: list[str] | None = None,
        attempt_count: int = 0,
        tools_called: list[str] | None = None,
        data_quality_state: str | None = None,
    ) -> None:
        await self._update_interpretation(
            interpretation_id,
            status="failed",
            updated_at=now,
            error=error,
            snapshot_id=snapshot_id,
            prompt_version=prompt_version,
            model=model,
            validation_status=validation_status,
            validation_errors=validation_errors,
            attempt_count=attempt_count,
            tools_called=tools_called,
            data_quality_state=data_quality_state,
        )

    async def _update_interpretation(self, interpretation_id: int, **fields: Any) -> None:
        stmt = (
            update(t.ai_interpretation)
            .where(t.ai_interpretation.c.id == interpretation_id)
            .values(**fields)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def get_by_uuid(self, analysis_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.ai_interpretation).where(t.ai_interpretation.c.uuid == analysis_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def interpretation_id_for_uuid(self, analysis_id: uuid.UUID) -> int | None:
        stmt = select(t.ai_interpretation.c.id).where(t.ai_interpretation.c.uuid == analysis_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row else None

    # ------------------------------------------------------------------ usage (budget ceiling)

    async def insert_usage(
        self,
        *,
        interpretation_id: int,
        now: datetime,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int | None,
        cost_usd: Decimal | None,
        attempt: int,
    ) -> None:
        row_uuid = uuid.uuid4()
        stmt = insert(t.ai_usage).values(
            uuid=row_uuid,
            created_at=now,
            interpretation_id=interpretation_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            attempt=attempt,
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def monthly_cost_usd(self, now: datetime) -> Decimal:
        """Sum ``ai.usage.cost_usd`` for the current UTC calendar month (TODO.md B3, ADR-0034/0038)
        — the budget ceiling is enforced against this live sum, never a separate, driftable
        counter (R3: no derived state that can silently diverge from its source)."""
        month_start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.coalesce(func.sum(t.ai_usage.c.cost_usd), 0)).where(
            t.ai_usage.c.created_at >= month_start
        )
        async with self.engine.connect() as conn:
            total = (await conn.execute(stmt)).scalar_one()
        return Decimal(total)

"""Daily Market Brief persistence (``ai.brief``), Phase 22 spec Section 9.

Follows ``cfi.analyst.repository.AnalystRepository``'s own style exactly (R13: reuse, do not
invent a parallel one): raw SQLAlchemy Core ``insert``/``update`` per write, each in its own short
transaction, never one shared ORM session. ``ai.snapshot`` and ``ai.usage`` are not duplicated —
this repository writes brief-owned ``ai.usage`` rows (via the ``brief_id`` column added in
migration 0008) and reads ``ai.snapshot`` directly, but the snapshot is inserted, and the monthly
budget ceiling is enforced, through the existing, unmodified ``AnalystRepository`` (Section 9:
"reuse Phase 21 audit infrastructure where appropriate rather than creating duplicate logging
systems") — see ``cfi.brief.service.BriefService``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t


class BriefRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ brief (job record)

    async def create_queued_brief(
        self,
        *,
        now: datetime,
        reporting_period_start: datetime,
        reporting_period_end: datetime,
        previous_brief_id: int | None,
    ) -> tuple[int, uuid.UUID]:
        """Create the ``queued`` row *before* the worker task runs, so its ``uuid`` is a stable
        ``brief_id`` the caller can return immediately (mirrors ``AnalystRepository.
        create_queued_interpretation``, Section 13/9)."""
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.ai_brief)
            .values(
                uuid=row_uuid,
                created_at=now,
                updated_at=now,
                reporting_period_start=reporting_period_start,
                reporting_period_end=reporting_period_end,
                snapshot_id=None,
                previous_brief_id=previous_brief_id,
                status="queued",
                prompt_version=None,
                analyst_version=None,
                model=None,
                response=None,
                validation_status=None,
                validation_errors=None,
                attempt_count=0,
                tools_called=None,
                data_quality_state=None,
                changes=None,
                error=None,
            )
            .returning(t.ai_brief.c.id)
        )
        async with self.engine.begin() as conn:
            brief_id = int((await conn.execute(stmt)).scalar_one())
        return brief_id, row_uuid

    async def mark_running(self, brief_id: int, *, now: datetime) -> None:
        await self._update_brief(brief_id, status="running", updated_at=now)

    async def mark_completed(
        self,
        brief_id: int,
        *,
        now: datetime,
        snapshot_id: int,
        prompt_version: str,
        analyst_version: str,
        model: str,
        response: dict[str, Any],
        validation_status: str,
        validation_errors: list[str],
        attempt_count: int,
        tools_called: list[str],
        data_quality_state: str,
        changes: dict[str, Any],
    ) -> None:
        await self._update_brief(
            brief_id,
            status="completed",
            updated_at=now,
            snapshot_id=snapshot_id,
            prompt_version=prompt_version,
            analyst_version=analyst_version,
            model=model,
            response=response,
            validation_status=validation_status,
            validation_errors=validation_errors,
            attempt_count=attempt_count,
            tools_called=tools_called,
            data_quality_state=data_quality_state,
            changes=changes,
        )

    async def mark_failed(
        self,
        brief_id: int,
        *,
        now: datetime,
        error: str,
        snapshot_id: int | None = None,
        prompt_version: str | None = None,
        analyst_version: str | None = None,
        model: str | None = None,
        validation_status: str | None = None,
        validation_errors: list[str] | None = None,
        attempt_count: int = 0,
        tools_called: list[str] | None = None,
        data_quality_state: str | None = None,
        changes: dict[str, Any] | None = None,
    ) -> None:
        await self._update_brief(
            brief_id,
            status="failed",
            updated_at=now,
            error=error,
            snapshot_id=snapshot_id,
            prompt_version=prompt_version,
            analyst_version=analyst_version,
            model=model,
            validation_status=validation_status,
            validation_errors=validation_errors,
            attempt_count=attempt_count,
            tools_called=tools_called,
            data_quality_state=data_quality_state,
            changes=changes,
        )

    async def _update_brief(self, brief_id: int, **fields: Any) -> None:
        stmt = update(t.ai_brief).where(t.ai_brief.c.id == brief_id).values(**fields)
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def get_by_uuid(self, brief_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.ai_brief).where(t.ai_brief.c.uuid == brief_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def get_by_id(self, brief_id: int) -> dict[str, Any] | None:
        stmt = select(t.ai_brief).where(t.ai_brief.c.id == brief_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def brief_id_for_uuid(self, brief_id: uuid.UUID) -> int | None:
        stmt = select(t.ai_brief.c.id).where(t.ai_brief.c.uuid == brief_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row else None

    async def latest_completed_brief(self) -> dict[str, Any] | None:
        """The most recent ``completed`` brief, by ``created_at`` — the comparison basis for the
        next brief's change detection (Section 5). ``None`` means no previous valid brief exists
        yet, which ``cfi.brief.changes.compute_changes`` turns into ``comparison_basis="none"``."""
        stmt = (
            select(t.ai_brief)
            .where(t.ai_brief.c.status == "completed")
            .order_by(t.ai_brief.c.created_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def get_snapshot_payload(self, snapshot_id: int) -> dict[str, Any] | None:
        """Read a previously stored ``ai.snapshot.payload`` verbatim — the exact comparison basis
        Section 5 requires. Writing a new snapshot row is Phase 21's own, unmodified
        ``AnalystRepository.insert_snapshot`` (``ai.snapshot`` is not brief-specific)."""
        stmt = select(t.ai_snapshot.c.payload).where(t.ai_snapshot.c.id == snapshot_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return row[0] if row else None

    # ------------------------------------------------------------------ usage (shared budget
    # ceiling, Section 9) — same ``ai.usage`` table as Phase 21, same unmodified
    # ``AnalystRepository.monthly_cost_usd`` query; only the owning column differs.

    async def insert_usage_for_brief(
        self,
        *,
        brief_id: int,
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
            interpretation_id=None,
            brief_id=brief_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            attempt=attempt,
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

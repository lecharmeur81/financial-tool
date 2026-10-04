"""Intelligence event persistence (``sig.intelligence_event``), Phase 35.

Follows ``cfi.alerts.repository.AlertRepository``'s own style exactly (R13: reuse, do not invent a
parallel one): raw SQLAlchemy Core ``insert``/``update``/``select`` per write, each in its own
short transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t


class IntelligenceEventRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ writes

    async def insert_event(
        self,
        *,
        now: datetime,
        observed_at: datetime,
        domain: str,
        event_type: str,
        severity: str,
        previous_value: str | None,
        current_value: str,
        change_magnitude: Any,
        detection_method: str,
        data_quality_state: str,
        component_status: str,
        dedup_key: str,
        correlation_key: str,
        snapshot_id: int | None,
        alert_id: int | None,
    ) -> tuple[int, uuid.UUID] | None:
        """Insert one event, or do nothing if ``alert_id`` already has one (idempotency: the one
        alert row a given evaluation decision writes is the deterministic anchor — see the
        migration's own docstring). Returns ``None`` on that conflict, never a fabricated id."""
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.intelligence_event)
            .values(
                uuid=row_uuid,
                created_at=now,
                observed_at=observed_at,
                domain=domain,
                event_type=event_type,
                severity=severity,
                previous_value=previous_value,
                current_value=current_value,
                change_magnitude=change_magnitude,
                detection_method=detection_method,
                data_quality_state=data_quality_state,
                component_status=component_status,
                dedup_key=dedup_key,
                correlation_key=correlation_key,
                snapshot_id=snapshot_id,
                alert_id=alert_id,
                status="new",
                ai_interpretation_id=None,
            )
            .on_conflict_do_nothing(index_elements=["alert_id"])
            .returning(t.intelligence_event.c.id)
        )
        async with self.engine.begin() as conn:
            row = (await conn.execute(stmt)).first()
        return (int(row[0]), row_uuid) if row else None

    async def mark_ai_requested(
        self, event_id: int, *, interpretation_id: int, now: datetime
    ) -> None:
        stmt = (
            update(t.intelligence_event)
            .where(t.intelligence_event.c.id == event_id)
            .values(status="ai_requested", ai_interpretation_id=interpretation_id)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ reads

    async def latest_ai_requested_at(self) -> datetime | None:
        """When the most recent AI analysis was requested from this service, across every domain
        — the one fact the AI-trigger policy's "not already analyzed recently" rule needs
        (``cfi.realtime.universe.AI_MIN_INTERVAL_SECONDS``)."""
        stmt = (
            select(t.intelligence_event.c.created_at)
            .where(t.intelligence_event.c.status == "ai_requested")
            .order_by(t.intelligence_event.c.created_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return row[0] if row else None

    async def get_event(self, event_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.intelligence_event).where(t.intelligence_event.c.uuid == event_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def list_events(
        self,
        *,
        domain: str | None,
        severity: str | None,
        event_type: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        stmt = select(t.intelligence_event).order_by(t.intelligence_event.c.created_at.desc())
        if domain is not None:
            stmt = stmt.where(t.intelligence_event.c.domain == domain)
        if severity is not None:
            stmt = stmt.where(t.intelligence_event.c.severity == severity)
        if event_type is not None:
            stmt = stmt.where(t.intelligence_event.c.event_type == event_type)
        if since is not None:
            stmt = stmt.where(t.intelligence_event.c.created_at >= since)
        stmt = stmt.limit(limit)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

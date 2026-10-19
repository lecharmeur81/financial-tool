"""Alert persistence (``usr.alert_event``), Phase 23 spec "Persistence"/"Deduplication / Cooldown".

Follows ``cfi.analyst.repository.AnalystRepository``'s own style exactly (R13: reuse, do not invent
a parallel one): raw SQLAlchemy Core ``insert``/``update`` per write, each in its own short
transaction. ``ai.snapshot`` is not duplicated here — alerts reference a snapshot row inserted
through the existing, unmodified ``AnalystRepository.insert_snapshot``.

The dedup/cooldown *decision* lives in ``cfi.alerts.lifecycle.decide`` (pure, DB-free); this
repository only reads the one fact that decision needs (the most recent non-terminal alert for a
dedup key) and executes whatever the decision says (insert, or insert-and-supersede)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.lifecycle import OPEN_STATUSES, ExistingAlert, user_transition_sources
from cfi.db import tables as t


class AlertRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ dedup lookup

    async def latest_active_for_key(self, dedup_key: str) -> ExistingAlert | None:
        """The most recent alert for this dedup key that is still ``active`` or
        ``acknowledged`` (not yet ``resolved``/``expired``) — the comparison basis
        ``cfi.alerts.lifecycle.decide`` needs. Only the two fields that decision reads are
        returned; the full row is fetched separately only when a write (supersede) is needed."""
        stmt = (
            select(t.alert_event.c.observed_value, t.alert_event.c.created_at)
            .where(
                t.alert_event.c.dedup_key == dedup_key,
                t.alert_event.c.status.in_(("active", "acknowledged")),
            )
            .order_by(t.alert_event.c.created_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return ExistingAlert(observed_value=row[0], timestamp=row[1]) if row else None

    async def latest_active_id_for_key(self, dedup_key: str) -> int | None:
        stmt = (
            select(t.alert_event.c.id)
            .where(
                t.alert_event.c.dedup_key == dedup_key,
                t.alert_event.c.status.in_(("active", "acknowledged")),
            )
            .order_by(t.alert_event.c.created_at.desc())
            .limit(1)
        )
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row else None

    async def active_entries_with_prefix(self, prefix: str) -> list[tuple[str, int]]:
        """Every dedup key (and its alert id) currently ``active``/``acknowledged`` whose key
        starts with ``prefix`` (e.g. ``"divergence:"``) — used to auto-resolve a flagged-state
        alert type (divergence/anomaly/capital_rotation) whose underlying flag the cycle's evidence
        EXPLICITLY shows cleared (an absent candidate alone is unknown, not cleared; see
        ``cfi.alerts.service.AlertService._auto_resolve_cleared``)."""
        stmt = select(t.alert_event.c.dedup_key, t.alert_event.c.id).where(
            t.alert_event.c.dedup_key.like(prefix + "%"),
            t.alert_event.c.status.in_(("active", "acknowledged")),
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [(r[0], int(r[1])) for r in rows]

    # ------------------------------------------------------------------ writes

    async def insert_alert(
        self,
        *,
        now: datetime,
        alert_type: str,
        severity: str,
        domain: str,
        dedup_key: str,
        trigger_condition: str,
        observed_value: str,
        reference_value: str | None,
        evidence_field_ids: list[str],
        snapshot_id: int | None,
        source_tool_id: str,
        component_status: str,
        data_quality_state: str,
    ) -> tuple[int, uuid.UUID]:
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.alert_event)
            .values(
                uuid=row_uuid,
                created_at=now,
                updated_at=now,
                alert_type=alert_type,
                severity=severity,
                domain=domain,
                dedup_key=dedup_key,
                trigger_condition=trigger_condition,
                observed_value=observed_value,
                reference_value=reference_value,
                evidence_field_ids=evidence_field_ids,
                snapshot_id=snapshot_id,
                source_tool_id=source_tool_id,
                component_status=component_status,
                data_quality_state=data_quality_state,
                status="active",
                superseded_by=None,
                acknowledged_at=None,
                resolved_at=None,
            )
            .returning(t.alert_event.c.id)
        )
        async with self.engine.begin() as conn:
            alert_id = int((await conn.execute(stmt)).scalar_one())
        return alert_id, row_uuid

    async def supersede(self, alert_id: int, *, now: datetime, superseded_by: int) -> None:
        """Re-arm: the prior alert for this dedup key is marked ``expired`` once a new one has
        been created to replace it (never deleted, R10 — the lifecycle is audit history)."""
        stmt = (
            update(t.alert_event)
            .where(t.alert_event.c.id == alert_id, t.alert_event.c.status.in_(OPEN_STATUSES))
            .values(status="expired", updated_at=now, superseded_by=superseded_by)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def resolve(self, alert_id: int, *, now: datetime) -> None:
        """The underlying condition no longer holds (a flagged-state alert type's flag cleared).
        Distinct from ``supersede``: no replacement alert exists — the state simply returned to
        normal."""
        stmt = (
            update(t.alert_event)
            .where(t.alert_event.c.id == alert_id, t.alert_event.c.status.in_(OPEN_STATUSES))
            .values(status="resolved", updated_at=now, resolved_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def set_status(self, alert_id: uuid.UUID, *, status: str, now: datetime) -> bool:
        """User-driven lifecycle transition (``acknowledged``/``resolved``) via the API.

        Guarded in the UPDATE itself (Phase 52): it applies only from a status
        ``cfi.alerts.lifecycle.user_transition`` permits, so a terminal alert is never reopened or
        re-stamped even if two requests race. Returns False when nothing changed."""
        sources = user_transition_sources(status)
        if not sources:
            return False
        values: dict[str, Any] = {"status": status, "updated_at": now}
        if status == "acknowledged":
            values["acknowledged_at"] = now
        elif status == "resolved":
            values["resolved_at"] = now
        stmt = (
            update(t.alert_event)
            .where(t.alert_event.c.uuid == alert_id, t.alert_event.c.status.in_(sources))
            .values(**values)
        )
        async with self.engine.begin() as conn:
            result = await conn.execute(stmt)
        return bool(result.rowcount)

    # ------------------------------------------------------------------ reads

    async def get_by_uuid(self, alert_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.alert_event).where(t.alert_event.c.uuid == alert_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def list_alerts(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        stmt = select(t.alert_event).order_by(t.alert_event.c.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(t.alert_event.c.status == status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

"""Decision journal persistence (``usr.decision_journal``), Phase 25 spec "Decision record" /
"Data integrity".

Follows ``cfi.paper.repository.PaperTradeRepository``'s own style exactly (R13: reuse, do not
invent a parallel one): raw SQLAlchemy Core ``insert``/``update`` per write, each in its own short
transaction. ``ai.snapshot``/``ai.brief``/``usr.paper_trade`` are not duplicated here — a journal
entry only references rows already inserted through their own existing, unmodified repositories.

Every ``update`` method here writes to an explicitly named, disjoint set of columns — the
decision-time columns (set once, by ``insert_decision`` only) are never touched by
``update_notes``/``record_outcome``/``link_paper_trade``/``unlink_paper_trade``/``cancel``, which
is what makes hindsight protection an invariant of this repository's own API shape, not just a
convention someone has to remember."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t


class DecisionJournalRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # -------------------------------------------------------------- create (decision-time)

    async def insert_decision(
        self,
        *,
        now: datetime,
        decision_time: datetime,
        asset: str,
        decision_type: str,
        thesis: str,
        expected_scenario: str | None,
        alternative_scenario: str | None,
        time_horizon: str | None,
        entry_price: Decimal | None,
        observed_price_at_decision: Decimal | None,
        invalidation_condition: str | None,
        key_risks: str | None,
        confidence: Decimal | None,
        notes: str | None,
        decision_snapshot_id: int | None,
        market_brief_id: int | None,
        relevant_alert_ids: list[str],
        market_regime_label: str | None,
    ) -> tuple[int, uuid.UUID]:
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.decision_journal)
            .values(
                uuid=row_uuid,
                created_at=now,
                updated_at=now,
                decision_time=decision_time,
                asset=asset,
                decision_type=decision_type,
                thesis=thesis,
                expected_scenario=expected_scenario,
                alternative_scenario=alternative_scenario,
                time_horizon=time_horizon,
                entry_price=entry_price,
                observed_price_at_decision=observed_price_at_decision,
                invalidation_condition=invalidation_condition,
                key_risks=key_risks,
                confidence=confidence,
                notes=notes,
                status="open",
                outcome=None,
                thesis_supported=None,
                thesis_contradicted=None,
                invalidation_occurred=None,
                evidence_changed_notes=None,
                actual_market_movement_text=None,
                actual_price_at_outcome=None,
                actual_market_movement_pct=None,
                lessons_notes=None,
                outcome_timestamp=None,
                decision_snapshot_id=decision_snapshot_id,
                market_brief_id=market_brief_id,
                relevant_alert_ids=relevant_alert_ids,
                market_regime_label=market_regime_label,
                paper_trade_id=None,
            )
            .returning(t.decision_journal.c.id)
        )
        async with self.engine.begin() as conn:
            decision_id = int((await conn.execute(stmt)).scalar_one())
        return decision_id, row_uuid

    # ---------------------------------------------------------- writes (disjoint, post-creation)

    async def update_notes(self, decision_id: int, *, now: datetime, notes: str | None) -> None:
        stmt = (
            update(t.decision_journal)
            .where(t.decision_journal.c.id == decision_id)
            .values(notes=notes, updated_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def record_outcome(
        self,
        decision_id: int,
        *,
        now: datetime,
        status: str,
        outcome: str | None,
        thesis_supported: bool | None,
        thesis_contradicted: bool | None,
        invalidation_occurred: bool | None,
        evidence_changed_notes: str | None,
        actual_market_movement_text: str | None,
        actual_price_at_outcome: Decimal | None,
        actual_market_movement_pct: Decimal | None,
        lessons_notes: str | None,
    ) -> None:
        stmt = (
            update(t.decision_journal)
            .where(t.decision_journal.c.id == decision_id)
            .values(
                status=status,
                updated_at=now,
                outcome=outcome,
                thesis_supported=thesis_supported,
                thesis_contradicted=thesis_contradicted,
                invalidation_occurred=invalidation_occurred,
                evidence_changed_notes=evidence_changed_notes,
                actual_market_movement_text=actual_market_movement_text,
                actual_price_at_outcome=actual_price_at_outcome,
                actual_market_movement_pct=actual_market_movement_pct,
                lessons_notes=lessons_notes,
                outcome_timestamp=now,
            )
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def cancel(self, decision_id: int, *, now: datetime) -> None:
        stmt = (
            update(t.decision_journal)
            .where(t.decision_journal.c.id == decision_id)
            .values(status="cancelled", updated_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def link_paper_trade(
        self, decision_id: int, *, now: datetime, paper_trade_id: int
    ) -> None:
        stmt = (
            update(t.decision_journal)
            .where(t.decision_journal.c.id == decision_id)
            .values(paper_trade_id=paper_trade_id, updated_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def unlink_paper_trade(self, decision_id: int, *, now: datetime) -> None:
        stmt = (
            update(t.decision_journal)
            .where(t.decision_journal.c.id == decision_id)
            .values(paper_trade_id=None, updated_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ reads

    async def get_by_uuid(self, decision_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.decision_journal).where(t.decision_journal.c.uuid == decision_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def list_decisions(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(t.decision_journal).order_by(t.decision_journal.c.created_at.desc()).limit(limit)
        )
        if status is not None:
            stmt = stmt.where(t.decision_journal.c.status == status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def all_for_stats(self) -> list[dict[str, Any]]:
        """Every decision, for ``cfi.journal.stats`` — a live aggregate over current rows, never
        a separately maintained counter that could drift (R3)."""
        stmt = select(t.decision_journal)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

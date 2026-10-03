"""Paper trade persistence (``usr.paper_trade``), Phase 24 spec "Core paper-trading record" /
"Trade lifecycle".

Follows ``cfi.alerts.repository.AlertRepository``/``cfi.analyst.repository.AnalystRepository``'s
own style exactly (R13: reuse, do not invent a parallel one): raw SQLAlchemy Core
``insert``/``update`` per write, each in its own short transaction. ``ai.snapshot`` and ``ai.brief``
are not duplicated here — a paper trade only references rows already inserted through the
existing, unmodified ``AnalystRepository.insert_snapshot`` and ``BriefRepository`` respectively.
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


class PaperTradeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ writes

    async def insert_trade(
        self,
        *,
        now: datetime,
        asset: str,
        direction: str,
        entry_time: datetime,
        entry_price_observed: Decimal,
        entry_price_execution: Decimal,
        entry_price_source: str,
        notional: Decimal,
        leverage: Decimal,
        margin: Decimal,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
        cost_model_version: str,
        strategy_tag: str | None,
        notes: str | None,
        decision_snapshot_id: int | None,
        market_brief_id: int | None,
        relevant_alert_ids: list[str],
    ) -> tuple[int, uuid.UUID]:
        row_uuid = uuid.uuid4()
        stmt = (
            insert(t.paper_trade)
            .values(
                uuid=row_uuid,
                created_at=now,
                updated_at=now,
                asset=asset,
                direction=direction,
                status="open",
                entry_time=entry_time,
                entry_price_observed=entry_price_observed,
                entry_price_execution=entry_price_execution,
                entry_price_source=entry_price_source,
                notional=notional,
                leverage=leverage,
                margin=margin,
                stop_loss=stop_loss,
                take_profit=take_profit,
                exit_time=None,
                exit_price_observed=None,
                exit_price_execution=None,
                exit_price_source=None,
                cost_model_version=cost_model_version,
                gross_pnl=None,
                slippage_cost=None,
                fees_total=None,
                realized_pnl=None,
                return_pct=None,
                max_favorable_move_pct=None,
                max_adverse_move_pct=None,
                strategy_tag=strategy_tag,
                notes=notes,
                decision_snapshot_id=decision_snapshot_id,
                market_brief_id=market_brief_id,
                relevant_alert_ids=relevant_alert_ids,
            )
            .returning(t.paper_trade.c.id)
        )
        async with self.engine.begin() as conn:
            trade_id = int((await conn.execute(stmt)).scalar_one())
        return trade_id, row_uuid

    async def close_trade(
        self,
        trade_id: int,
        *,
        now: datetime,
        exit_time: datetime,
        exit_price_observed: Decimal,
        exit_price_execution: Decimal,
        exit_price_source: str,
        gross_pnl: Decimal,
        slippage_cost: Decimal,
        fees_total: Decimal,
        realized_pnl: Decimal,
        return_pct: Decimal,
        max_favorable_move_pct: Decimal | None,
        max_adverse_move_pct: Decimal | None,
    ) -> None:
        stmt = (
            update(t.paper_trade)
            .where(t.paper_trade.c.id == trade_id)
            .values(
                status="closed",
                updated_at=now,
                exit_time=exit_time,
                exit_price_observed=exit_price_observed,
                exit_price_execution=exit_price_execution,
                exit_price_source=exit_price_source,
                gross_pnl=gross_pnl,
                slippage_cost=slippage_cost,
                fees_total=fees_total,
                realized_pnl=realized_pnl,
                return_pct=return_pct,
                max_favorable_move_pct=max_favorable_move_pct,
                max_adverse_move_pct=max_adverse_move_pct,
            )
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    async def cancel_trade(self, trade_id: int, *, now: datetime) -> None:
        stmt = (
            update(t.paper_trade)
            .where(t.paper_trade.c.id == trade_id)
            .values(status="cancelled", updated_at=now)
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt)

    # ------------------------------------------------------------------ reads

    async def get_by_uuid(self, trade_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(t.paper_trade).where(t.paper_trade.c.uuid == trade_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def trade_id_for_uuid(self, trade_id: uuid.UUID) -> int | None:
        stmt = select(t.paper_trade.c.id).where(t.paper_trade.c.uuid == trade_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row else None

    async def list_trades(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        stmt = select(t.paper_trade).order_by(t.paper_trade.c.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(t.paper_trade.c.status == status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def list_open(self) -> list[dict[str, Any]]:
        stmt = (
            select(t.paper_trade)
            .where(t.paper_trade.c.status == "open")
            .order_by(t.paper_trade.c.entry_time.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def list_closed(self) -> list[dict[str, Any]]:
        """Every closed trade, for ``cfi.paper.stats.performance_stats`` — a live aggregate over
        current rows, never a separately maintained counter that could drift (R3)."""
        stmt = (
            select(t.paper_trade)
            .where(t.paper_trade.c.status == "closed")
            .order_by(t.paper_trade.c.exit_time.asc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def counts_by_status(self) -> dict[str, int]:
        stmt = select(t.paper_trade.c.status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        counts: dict[str, int] = {}
        for (status,) in rows:
            counts[status] = counts.get(status, 0) + 1
        return counts
